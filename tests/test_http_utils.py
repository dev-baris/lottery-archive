"""HTTP retry policy, decoding and resource cleanup without network requests."""

import contextlib
import io
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, PropertyMock, call, patch

import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from http_utils import BROWSER_HEADERS, fetch_url

URL = "https://example.invalid/archive"


def response(status=200, content=b"archive", headers=None):
    result = requests.Response()
    result.url = URL
    result.status_code = status
    result._content = content
    result._content_consumed = True
    result.headers.update(headers or {})
    result.close = Mock(wraps=result.close)
    return result


class TestFetchURL(unittest.TestCase):
    def setUp(self):
        self.session = requests.Session()
        self.session.get = Mock()
        self.session.close = Mock(wraps=self.session.close)
        self.session_factory = self.enterContext(
            patch("http_utils.requests.Session", return_value=self.session)
        )
        self.sleep = self.enterContext(patch("http_utils.time.sleep"))
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))

    def test_success_closes_response_and_session(self):
        result = response()
        self.session.get.return_value = result
        self.assertEqual(fetch_url(URL), "archive")
        self.session.get.assert_called_once_with(URL, timeout=30)
        self.assertEqual(self.session.headers["User-Agent"], BROWSER_HEADERS["User-Agent"])
        result.close.assert_called_once()
        self.session.close.assert_called_once()
        self.sleep.assert_not_called()

    def test_explicit_charset_wins_over_apparent_encoding(self):
        result = response(content="ä".encode("utf-8"), headers={"Content-Type": 'text/html; charset="utf-8"'})
        self.session.get.return_value = result
        with patch.object(requests.Response, "apparent_encoding", new_callable=PropertyMock) as apparent:
            apparent.return_value = "windows-1252"
            self.assertEqual(fetch_url(URL), "ä")
            apparent.assert_not_called()

    def test_missing_charset_uses_detected_legacy_encoding(self):
        result = response(content=b"M\xe4rz", headers={"Content-Type": "text/html"})
        self.session.get.return_value = result
        with patch.object(requests.Response, "apparent_encoding", new_callable=PropertyMock) as apparent:
            apparent.return_value = "windows-1252"
            self.assertEqual(fetch_url(URL), "März")

    def test_missing_charset_and_detection_use_legacy_fallback(self):
        self.session.get.return_value = response(content=b"M\xe4rz")
        with patch.object(requests.Response, "apparent_encoding", new_callable=PropertyMock) as apparent:
            apparent.return_value = None
            self.assertEqual(fetch_url(URL), "März")

    def test_transient_statuses_are_retried(self):
        for status in (408, 429, 500, 502, 503, 504):
            with self.subTest(status=status):
                bad, good = response(status), response()
                self.session.get.reset_mock(side_effect=True)
                self.session.get.side_effect = [bad, good]
                self.sleep.reset_mock()
                self.assertEqual(fetch_url(URL, retries=2), "archive")
                self.assertEqual(self.session.get.call_count, 2)
                self.sleep.assert_called_once_with(2.0)
                bad.close.assert_called_once()
                good.close.assert_called_once()

    def test_permanent_statuses_fail_immediately_with_response(self):
        for status in (400, 401, 403, 404, 410, 422, 501):
            with self.subTest(status=status):
                bad = response(status)
                self.session.get.reset_mock(side_effect=True)
                self.session.get.return_value = bad
                with self.assertRaises(requests.HTTPError) as caught:
                    fetch_url(URL)
                self.assertIs(caught.exception.response, bad)
                self.session.get.assert_called_once()
                bad.close.assert_called_once()
        self.sleep.assert_not_called()

    def test_retryable_transfer_errors(self):
        for error in (
            requests.ConnectionError("disconnected"),
            requests.ConnectTimeout("connect timeout"),
            requests.ReadTimeout("read timeout"),
            requests.exceptions.ChunkedEncodingError("partial response"),
        ):
            with self.subTest(error=type(error).__name__):
                self.session.get.reset_mock(side_effect=True)
                self.session.get.side_effect = [error, response()]
                self.assertEqual(fetch_url(URL, backoff=0), "archive")
                self.assertEqual(self.session.get.call_count, 2)

    def test_permanent_request_errors_fail_immediately(self):
        for error in (
            requests.exceptions.InvalidURL("invalid URL"),
            requests.exceptions.InvalidSchema("unknown scheme"),
            requests.exceptions.SSLError("certificate verification failed"),
            requests.TooManyRedirects("redirect loop"),
            requests.RequestException("nontransient error"),
            requests.HTTPError("no response"),
        ):
            with self.subTest(error=type(error).__name__):
                self.session.get.reset_mock(side_effect=True)
                self.session.get.side_effect = error
                with self.assertRaises(type(error)):
                    fetch_url(URL)
                self.session.get.assert_called_once()
        self.sleep.assert_not_called()

    def test_exhaustion_raises_last_error_and_closes_session(self):
        errors = [requests.Timeout(str(index)) for index in range(3)]
        self.session.get.side_effect = errors
        with self.assertRaises(requests.Timeout) as caught:
            fetch_url(URL)
        self.assertIs(caught.exception, errors[-1])
        self.assertEqual(self.sleep.call_args_list, [call(2.0), call(4.0)])
        self.session.close.assert_called_once()

    def test_single_attempt_does_not_sleep(self):
        self.session.get.side_effect = requests.Timeout("timeout")
        with self.assertRaises(requests.Timeout):
            fetch_url(URL, retries=1)
        self.session.get.assert_called_once()
        self.sleep.assert_not_called()

    def test_backoff_is_exponential_and_bounded(self):
        self.session.get.side_effect = [requests.Timeout("timeout")] * 3 + [response()]
        self.assertEqual(fetch_url(URL, retries=4, backoff=20), "archive")
        self.assertEqual(self.sleep.call_args_list, [call(20), call(40), call(60)])

    def test_numeric_retry_after_is_honored(self):
        self.session.get.side_effect = [response(429, headers={"Retry-After": "10"}), response()]
        self.assertEqual(fetch_url(URL), "archive")
        self.sleep.assert_called_once_with(10.0)

    def test_http_date_retry_after_is_honored(self):
        self.session.get.side_effect = [
            response(503, headers={"Retry-After": "Sun, 20 Sep 2026 12:00:20 GMT"}),
            response(),
        ]
        with patch("http_utils.datetime") as clock:
            clock.now.return_value = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
            self.assertEqual(fetch_url(URL), "archive")
        self.sleep.assert_called_once_with(20.0)

    def test_invalid_retry_after_uses_backoff(self):
        for header in ("nonsense", "-10", "nan", "1.5"):
            with self.subTest(header=header):
                self.sleep.reset_mock()
                self.session.get.side_effect = [response(503, headers={"Retry-After": header}), response()]
                self.assertEqual(fetch_url(URL), "archive")
                self.sleep.assert_called_once_with(2.0)

    def test_long_retry_after_surfaces_error_without_retrying_early(self):
        bad = response(429, headers={"Retry-After": "120"})
        self.session.get.return_value = bad
        with self.assertRaises(requests.HTTPError):
            fetch_url(URL)
        self.session.get.assert_called_once()
        self.sleep.assert_not_called()
        bad.close.assert_called_once()
        self.session.close.assert_called_once()

    def test_invalid_retry_count_fails_before_opening_session(self):
        for retries in (0, -1, 1.5, True, None, "3"):
            with self.subTest(retries=retries), self.assertRaises(ValueError):
                fetch_url(URL, retries=retries)
        self.session_factory.assert_not_called()

    def test_invalid_backoff_fails_before_opening_session(self):
        for backoff in (-1, float("nan"), float("inf"), True, None, "2", 10**1000):
            with self.subTest(backoff=backoff), self.assertRaises(ValueError):
                fetch_url(URL, backoff=backoff)
        self.session_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
