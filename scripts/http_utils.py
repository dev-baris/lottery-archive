#!/usr/bin/env python3
"""Shared HTTP requests with bounded retries and deterministic cleanup."""

import math
import sys
import time
from datetime import datetime, timezone
from email.message import Message
from email.utils import parsedate_to_datetime

import requests
from requests import HTTPError, RequestException

__all__ = ["fetch_url", "BROWSER_HEADERS", "HTTPError", "RequestException"]

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
MAX_RETRY_DELAY = 60.0


def _retry_after(response: requests.Response | None) -> float | None:
    """Read Retry-After as either seconds or an HTTP date, ignoring bad values."""
    if response is None:
        return None
    value = response.headers.get("Retry-After", "").strip()
    if value.isdecimal():
        try:
            return float(value)
        except (ValueError, OverflowError):
            return None
    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def fetch_url(url: str, retries: int = 3, backoff: float = 2.0) -> str:
    """Fetch text, making at most ``retries`` total attempts.

    Retry connection errors, timeouts, interrupted transfers, and transient HTTP
    statuses. Permanent HTTP errors (including missing archives), malformed URLs,
    and TLS verification failures propagate immediately. ``backoff`` is the first
    retry delay in seconds; later delays double, capped at 60 seconds. Honor
    Retry-After up to that limit; longer server waits propagate the HTTP error.

    A declared response charset takes precedence over detected legacy encodings.
    Sessions and responses close on success and on every failure path.
    """
    if isinstance(retries, bool) or not isinstance(retries, int) or retries < 1:
        raise ValueError("retries must be an integer of at least 1")
    if isinstance(backoff, bool) or not isinstance(backoff, (int, float)):
        raise ValueError("backoff must be a finite, nonnegative number")
    try:
        backoff = float(backoff)
    except OverflowError as exc:
        raise ValueError("backoff must be a finite, nonnegative number") from exc
    if not math.isfinite(backoff) or backoff < 0:
        raise ValueError("backoff must be a finite, nonnegative number")

    delay = min(backoff, MAX_RETRY_DELAY)
    with requests.Session() as session:
        session.headers.update(BROWSER_HEADERS)
        for attempt in range(1, retries + 1):
            try:
                with session.get(url, timeout=30) as response:
                    response.raise_for_status()
                    content_type = Message()
                    content_type["content-type"] = response.headers.get("Content-Type", "")
                    response.encoding = (
                        content_type.get_content_charset()
                        or response.apparent_encoding
                        or "windows-1252"
                    )
                    return response.text
            except RequestException as exc:
                if isinstance(exc, HTTPError):
                    if (
                        exc.response is None
                        or exc.response.status_code not in RETRYABLE_STATUSES
                    ):
                        raise
                elif isinstance(exc, requests.exceptions.SSLError) or not isinstance(
                    exc,
                    (
                        requests.ConnectionError,
                        requests.Timeout,
                        requests.exceptions.ChunkedEncodingError,
                    ),
                ):
                    raise
                if attempt == retries:
                    raise
                server_delay = _retry_after(exc.response)
                if server_delay is not None and server_delay > MAX_RETRY_DELAY:
                    raise
                wait = max(delay, server_delay or 0.0)
                print(
                    f"  Attempt {attempt} failed ({exc}). Retrying in {wait:g}s...",
                    file=sys.stderr,
                )
                time.sleep(wait)
                delay = min(delay * 2, MAX_RETRY_DELAY)

    raise RuntimeError("HTTP retry loop exited without a result")  # pragma: no cover
