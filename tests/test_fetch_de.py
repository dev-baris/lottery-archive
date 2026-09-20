"""
Unit tests for fetch_lotto_de_6aus49.py

All tests are offline — no network requests are made.
"""

import contextlib
import io
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import fetch_lotto_de_6aus49 as fetch_de
from fetch_lotto_de_6aus49 import Draw


# ---------------------------------------------------------------------------
# HTML fixtures (mimics lottozahlenonline.de structure)
# ---------------------------------------------------------------------------

def _make_row(draw_date: str, numbers: list[int], superzahl: str = "5") -> str:
    """Build one zahlensuche_rahmen div with the given data."""
    zahl_divs = "".join(
        f'<div class="zahlensuche_zahl">{n}</div>' for n in numbers
    )
    return (
        f'<div class="zahlensuche_rahmen">'
        f'<div class="zahlensuche_nr">1</div>'
        f'<time class="zahlensuche_datum" datetime="{draw_date}">'
        f'{draw_date}</time>'
        f'<div class="zahlensuche_tag">Sa</div>'
        f'{zahl_divs}'
        f'<div class="zahlensuche_zz">{superzahl}</div>'
        f'</div>'
    )


VALID_ROW_1 = _make_row("2025-01-04", [2, 6, 24, 30, 36, 45], "2")
VALID_ROW_2 = _make_row("2025-01-08", [9, 27, 28, 30, 45, 49], "6")
VALID_ROW_3 = _make_row("2025-01-11", [10, 22, 26, 27, 30, 33], "8")

PAGE_THREE_DRAWS = f"<html><body>{VALID_ROW_1}{VALID_ROW_2}{VALID_ROW_3}</body></html>"
PAGE_ONE_DRAW   = f"<html><body>{VALID_ROW_1}</body></html>"
PAGE_EMPTY      = "<html><body></body></html>"

ROW_MISSING_SZ = (
    '<div class="zahlensuche_rahmen">'
    '<time class="zahlensuche_datum" datetime="2000-01-01">2000-01-01</time>'
    '<div class="zahlensuche_zahl">1</div>'
    '<div class="zahlensuche_zahl">2</div>'
    '<div class="zahlensuche_zahl">3</div>'
    '<div class="zahlensuche_zahl">4</div>'
    '<div class="zahlensuche_zahl">5</div>'
    '<div class="zahlensuche_zahl">6</div>'
    '<div class="zahlensuche_zz"></div>'    # every retained draw requires this
    '</div>'
)

ROW_INVALID_RANGE = _make_row("2025-03-01", [0, 2, 3, 4, 5, 6], "5")   # n1=0
ROW_INVALID_SZ    = _make_row("2025-03-02", [1, 2, 3, 4, 5, 6], "10")  # sz=10
ROW_DUPLICATE_NR  = _make_row("2025-03-03", [1, 1, 3, 4, 5, 6], "5")   # dup

ROW_FIVE_NUMBERS = (
    '<div class="zahlensuche_rahmen">'
    '<time class="zahlensuche_datum" datetime="2025-04-01">2025-04-01</time>'
    '<div class="zahlensuche_zahl">1</div>'
    '<div class="zahlensuche_zahl">2</div>'
    '<div class="zahlensuche_zahl">3</div>'
    '<div class="zahlensuche_zahl">4</div>'
    '<div class="zahlensuche_zahl">5</div>'
    '<div class="zahlensuche_zz">3</div>'
    '</div>'
)


# ---------------------------------------------------------------------------
# parse_year_page
# ---------------------------------------------------------------------------

class TestParseYearPage(unittest.TestCase):
    def test_returns_three_draws(self):
        draws = fetch_de.parse_year_page(PAGE_THREE_DRAWS)
        self.assertEqual(len(draws), 3)

    def test_first_draw_date(self):
        draws = fetch_de.parse_year_page(PAGE_THREE_DRAWS)
        self.assertEqual(draws[0].date, "2025-01-04")

    def test_first_draw_numbers(self):
        draws = fetch_de.parse_year_page(PAGE_THREE_DRAWS)
        d = draws[0]
        self.assertEqual((d.n1, d.n2, d.n3, d.n4, d.n5, d.n6), (2, 6, 24, 30, 36, 45))

    def test_first_draw_superzahl(self):
        draws = fetch_de.parse_year_page(PAGE_THREE_DRAWS)
        self.assertEqual(draws[0].superzahl, 2)

    def test_empty_page_returns_empty_list(self):
        self.assertEqual(fetch_de.parse_year_page(PAGE_EMPTY), [])

    def test_single_draw_page(self):
        draws = fetch_de.parse_year_page(PAGE_ONE_DRAW)
        self.assertEqual(len(draws), 1)

    def test_empty_superzahl_rejected_at_archive_start(self):
        html = f"<html><body>{ROW_MISSING_SZ}</body></html>"
        with self.assertRaisesRegex(ValueError, "missing superzahl"):
            fetch_de.parse_year_page(html, strict=True)

    def test_archive_start_is_inclusive(self):
        html = _make_row("2000-01-01", [1, 2, 3, 4, 5, 6], "0")
        self.assertEqual(
            fetch_de.parse_year_page(html, strict=True),
            [Draw("2000-01-01", 1, 2, 3, 4, 5, 6, 0)],
        )

    def test_pre_2000_source_row_rejected_in_strict_mode(self):
        html = _make_row("1999-12-31", [1, 2, 3, 4, 5, 6])
        with self.assertRaisesRegex(ValueError, "2000-01-01"):
            fetch_de.parse_year_page(html, strict=True)

    def test_diagnostic_parser_does_not_return_pre_2000_draws(self):
        html = _make_row("1999-12-31", [1, 2, 3, 4, 5, 6]) + VALID_ROW_1
        with contextlib.redirect_stderr(io.StringIO()):
            draws = fetch_de.parse_year_page(html)
        self.assertEqual([draw.date for draw in draws], ["2025-01-04"])

    def test_invalid_number_range_skipped(self):
        html = f"<html><body>{ROW_INVALID_RANGE}</body></html>"
        with contextlib.redirect_stderr(io.StringIO()):
            draws = fetch_de.parse_year_page(html)
        self.assertEqual(draws, [])

    def test_invalid_superzahl_skipped(self):
        html = f"<html><body>{ROW_INVALID_SZ}</body></html>"
        with contextlib.redirect_stderr(io.StringIO()):
            draws = fetch_de.parse_year_page(html)
        self.assertEqual(draws, [])

    def test_duplicate_numbers_skipped(self):
        html = f"<html><body>{ROW_DUPLICATE_NR}</body></html>"
        with contextlib.redirect_stderr(io.StringIO()):
            draws = fetch_de.parse_year_page(html)
        self.assertEqual(draws, [])

    def test_row_with_five_numbers_skipped(self):
        html = f"<html><body>{ROW_FIVE_NUMBERS}</body></html>"
        with contextlib.redirect_stderr(io.StringIO()):
            draws = fetch_de.parse_year_page(html)
        self.assertEqual(draws, [])

    def test_valid_rows_mixed_with_invalid_parsed_correctly(self):
        html = (
            f"<html><body>"
            f"{VALID_ROW_1}{ROW_INVALID_RANGE}{VALID_ROW_2}"
            f"</body></html>"
        )
        with contextlib.redirect_stderr(io.StringIO()):
            draws = fetch_de.parse_year_page(html)
        self.assertEqual(len(draws), 2)
        self.assertEqual(draws[0].date, "2025-01-04")
        self.assertEqual(draws[1].date, "2025-01-08")


# ---------------------------------------------------------------------------
# validate_draw
# ---------------------------------------------------------------------------

class TestValidateDraw(unittest.TestCase):
    def _make(self, numbers=(1, 2, 3, 4, 5, 6), superzahl: int | None = 5):
        return Draw("2025-01-01", *numbers, superzahl)

    def test_valid_draw_passes(self):
        valid, reason = fetch_de.validate_draw(self._make())
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_archive_cutoff_is_inclusive(self):
        for draw_date, expected in [("1999-12-31", False), ("2000-01-01", True)]:
            with self.subTest(date=draw_date):
                valid, reason = fetch_de.validate_draw(self._make()._replace(date=draw_date))
                self.assertEqual(valid, expected, reason)

    def test_none_superzahl_fails_at_archive_start(self):
        valid, reason = fetch_de.validate_draw(self._make(superzahl=None)._replace(date="2000-01-01"))
        self.assertFalse(valid)
        self.assertIn("missing superzahl", reason)

    def test_calendar_validation_handles_leap_year_2000(self):
        for draw_date, expected in [("2000-02-29", True), ("2001-02-29", False)]:
            with self.subTest(date=draw_date):
                valid, reason = fetch_de.validate_draw(self._make()._replace(date=draw_date))
                self.assertEqual(valid, expected, reason)

    def test_modern_draw_requires_superzahl(self):
        self.assertFalse(fetch_de.validate_draw(self._make(superzahl=None))[0])

    def test_impossible_calendar_date_fails(self):
        self.assertFalse(fetch_de.validate_draw(self._make()._replace(date="2025-02-30"))[0])

    def test_boundary_numbers_pass(self):
        valid, _ = fetch_de.validate_draw(self._make(numbers=(1, 2, 3, 4, 5, 49)))
        self.assertTrue(valid)

    def test_superzahl_zero_passes(self):
        valid, _ = fetch_de.validate_draw(self._make(superzahl=0))
        self.assertTrue(valid)

    def test_superzahl_nine_passes(self):
        valid, _ = fetch_de.validate_draw(self._make(superzahl=9))
        self.assertTrue(valid)

    def test_duplicate_numbers_fail(self):
        valid, reason = fetch_de.validate_draw(self._make(numbers=(1, 1, 3, 4, 5, 6)))
        self.assertFalse(valid)
        self.assertIn("duplicate", reason)

    def test_number_zero_fails(self):
        valid, reason = fetch_de.validate_draw(self._make(numbers=(0, 2, 3, 4, 5, 6)))
        self.assertFalse(valid)
        self.assertIn("out of range", reason)

    def test_number_50_fails(self):
        valid, reason = fetch_de.validate_draw(self._make(numbers=(1, 2, 3, 4, 5, 50)))
        self.assertFalse(valid)
        self.assertIn("out of range", reason)

    def test_superzahl_minus1_fails(self):
        valid, reason = fetch_de.validate_draw(self._make(superzahl=-1))
        self.assertFalse(valid)
        self.assertIn("superzahl", reason)

    def test_superzahl_10_fails(self):
        valid, reason = fetch_de.validate_draw(self._make(superzahl=10))
        self.assertFalse(valid)
        self.assertIn("superzahl", reason)


# ---------------------------------------------------------------------------
# CSV I/O: load_existing_draws / write_draws
# ---------------------------------------------------------------------------

class TestCsvIO(unittest.TestCase):
    def _draw(self, date="2025-01-04", numbers=(2, 6, 24, 30, 36, 45), superzahl=2):
        return Draw(date, *numbers, superzahl)

    def test_load_existing_draws_missing_file_returns_empty(self):
        from pathlib import Path
        result = fetch_de.load_existing_draws(Path("/nonexistent/path.csv"))
        self.assertEqual(result, [])

    def test_load_existing_dates_missing_file_returns_empty(self):
        from pathlib import Path
        result = fetch_de.load_existing_dates(Path("/nonexistent/path.csv"))
        self.assertEqual(result, set())

    def test_write_and_reload_roundtrip(self):
        import tempfile, pathlib
        draw = self._draw()
        with tempfile.TemporaryDirectory() as tmp:
            real_path = pathlib.Path(tmp) / "results.csv"
            original = fetch_de.RESULTS_CSV
            fetch_de.RESULTS_CSV = real_path
            try:
                fetch_de.write_draws([draw])
                loaded = fetch_de.load_existing_draws(real_path)
            finally:
                fetch_de.RESULTS_CSV = original

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].date, "2025-01-04")
        self.assertEqual(loaded[0].n1, 2)
        self.assertEqual(loaded[0].superzahl, 2)

    def test_write_pre_2000_draw_does_not_modify_existing_file(self):
        """Manual writes cannot reintroduce dates removed by the archive policy."""
        with tempfile.TemporaryDirectory() as tmp:
            real_path = Path(tmp) / "results.csv"
            with patch.object(fetch_de, "RESULTS_CSV", real_path):
                fetch_de.write_draws([self._draw(date="2000-01-01")])
                original = real_path.read_bytes()
                with self.assertRaisesRegex(ValueError, "2000-01-01"):
                    fetch_de.write_draws([self._draw(date="1999-12-31")])
                self.assertEqual(real_path.read_bytes(), original)

    def test_write_missing_superzahl_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            real_path = Path(tmp) / "results.csv"
            with patch.object(fetch_de, "RESULTS_CSV", real_path):
                with self.assertRaisesRegex(ValueError, "missing superzahl"):
                    fetch_de.write_draws([self._draw(date="2000-01-01", superzahl=None)])
            self.assertFalse(real_path.exists())

    def test_stored_pre_2000_draw_blocks_reads_and_merges(self):
        with tempfile.TemporaryDirectory() as tmp:
            real_path = Path(tmp) / "results.csv"
            real_path.write_text(
                "date,n1,n2,n3,n4,n5,n6,superzahl\n1999-12-31,1,2,3,4,5,6,2\n",
                encoding="utf-8",
            )
            original = real_path.read_bytes()
            with self.assertRaisesRegex(ValueError, "2000-01-01"):
                fetch_de.load_existing_dates(real_path)
            with patch.object(fetch_de, "RESULTS_CSV", real_path):
                with self.assertRaisesRegex(ValueError, "2000-01-01"):
                    fetch_de.write_draws([self._draw(date="2000-01-01")])
            self.assertEqual(real_path.read_bytes(), original)

    def test_stored_missing_superzahl_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            real_path = Path(tmp) / "results.csv"
            real_path.write_text(
                "date,n1,n2,n3,n4,n5,n6,superzahl\n2000-01-01,1,2,3,4,5,6,\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "missing superzahl"):
                fetch_de.load_existing_draws(real_path)

    def test_write_draws_merges_with_existing(self):
        """Writing new draws must not overwrite draws already in the file."""
        import tempfile, pathlib
        draw1 = self._draw(date="2025-01-04")
        draw2 = self._draw(date="2025-01-08", numbers=(9, 27, 28, 30, 45, 49), superzahl=6)
        with tempfile.TemporaryDirectory() as tmp:
            real_path = pathlib.Path(tmp) / "results.csv"
            original = fetch_de.RESULTS_CSV
            fetch_de.RESULTS_CSV = real_path
            try:
                fetch_de.write_draws([draw1])
                fetch_de.write_draws([draw2])
                loaded = fetch_de.load_existing_draws(real_path)
            finally:
                fetch_de.RESULTS_CSV = original

        self.assertEqual(len(loaded), 2)

    def test_write_draws_sorted_by_date(self):
        """Draws must be written in chronological order regardless of input order."""
        import tempfile, pathlib
        draw_late = self._draw(date="2025-01-08")
        draw_early = self._draw(date="2025-01-04", numbers=(1, 2, 3, 4, 5, 6))
        with tempfile.TemporaryDirectory() as tmp:
            real_path = pathlib.Path(tmp) / "results.csv"
            original = fetch_de.RESULTS_CSV
            fetch_de.RESULTS_CSV = real_path
            try:
                fetch_de.write_draws([draw_late, draw_early])
                loaded = fetch_de.load_existing_draws(real_path)
            finally:
                fetch_de.RESULTS_CSV = original

        self.assertEqual(loaded[0].date, "2025-01-04")
        self.assertEqual(loaded[1].date, "2025-01-08")

    def test_write_draws_overwrites_on_date_collision(self):
        """Writing a draw for an existing date replaces the old draw."""
        import tempfile, pathlib
        original_draw = self._draw(date="2025-01-04", numbers=(1, 2, 3, 4, 5, 6))
        updated_draw = self._draw(date="2025-01-04", numbers=(9, 27, 28, 30, 45, 49))
        with tempfile.TemporaryDirectory() as tmp:
            real_path = pathlib.Path(tmp) / "results.csv"
            original = fetch_de.RESULTS_CSV
            fetch_de.RESULTS_CSV = real_path
            try:
                fetch_de.write_draws([original_draw])
                fetch_de.write_draws([updated_draw])
                loaded = fetch_de.load_existing_draws(real_path)
            finally:
                fetch_de.RESULTS_CSV = original

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].n1, 9)


# ---------------------------------------------------------------------------
# fetch_new_draws deduplication
# ---------------------------------------------------------------------------

class TestFetchNewDraws(unittest.TestCase):
    def test_init_and_empty_bootstrap_start_at_2000(self):
        for init, stored_dates in [(True, {"2025-01-04"}), (False, set())]:
            with self.subTest(init=init, stored_dates=stored_dates), \
                 patch.object(fetch_de, "load_existing_dates", return_value=set(stored_dates)), \
                 patch.object(fetch_de, "fetch_year", return_value=[]) as fetch_year, \
                 patch.object(fetch_de.time, "sleep"), \
                 patch.object(fetch_de, "date", wraps=date) as clock:
                clock.today.return_value = date(2026, 9, 20)
                fetch_de.fetch_new_draws(init=init)
                self.assertEqual(
                    [call.args[0] for call in fetch_year.call_args_list],
                    list(range(2000, 2027)),
                )

    def test_previous_year_recovery_does_not_cross_archive_start(self):
        with patch.object(fetch_de, "load_existing_dates", return_value={"2000-01-01"}), \
             patch.object(fetch_de, "fetch_year", return_value=[]) as fetch_year, \
             patch.object(fetch_de, "date", wraps=date) as clock:
            clock.today.return_value = date(2000, 9, 20)
            fetch_de.fetch_new_draws()
        self.assertEqual([call.args[0] for call in fetch_year.call_args_list], [2000])

    def test_invalid_year_rejected_before_http(self):
        for year in [1999, 2027, 0, True, 2000.0, "2000", None]:
            with self.subTest(year=year), \
                 patch.object(fetch_de, "fetch_url") as fetch_url, \
                 patch.object(fetch_de, "date", wraps=date) as clock:
                clock.today.return_value = date(2026, 9, 20)
                with self.assertRaisesRegex(ValueError, "between 2000 and 2026"):
                    fetch_de.fetch_year(year, set())
                fetch_url.assert_not_called()

    def test_first_archive_year_can_be_fetched(self):
        html = _make_row("2000-01-01", [1, 2, 3, 4, 5, 6])
        with patch.object(fetch_de, "fetch_url", return_value=html) as fetch_url:
            draws = fetch_de.fetch_year(2000, set())
        fetch_url.assert_called_once_with(f"{fetch_de.BASE_URL}?j=2000")
        self.assertEqual([draw.date for draw in draws], ["2000-01-01"])

    def test_existing_dates_are_excluded(self):
        """Draws whose date is already in results.csv must not be returned."""
        # PAGE_THREE_DRAWS has dates 2025-01-04, 2025-01-08, 2025-01-11
        pre_existing = {"2025-01-04", "2025-01-08"}

        with patch("fetch_lotto_de_6aus49.load_existing_dates",
                   return_value=set(pre_existing)), \
             patch("fetch_lotto_de_6aus49.fetch_url",
                   side_effect=[PAGE_THREE_DRAWS, PAGE_THREE_DRAWS.replace("2025-", "2026-")]), \
             patch("fetch_lotto_de_6aus49.date", wraps=date) as clock:
            clock.today.return_value = date(2026, 9, 20)
            draws = fetch_de.fetch_new_draws(init=False)

        self.assertFalse(any(d.date in pre_existing for d in draws))
        self.assertEqual(len(draws), 4)
        self.assertEqual(draws[0].date, "2025-01-11")

    def test_empty_response_fails_instead_of_reporting_no_updates(self):
        with patch.object(fetch_de, "fetch_url", return_value=PAGE_EMPTY):
            with self.assertRaisesRegex(ValueError, "no valid draws"):
                fetch_de.fetch_year(2025, set())

    def test_wrong_archive_year_fails(self):
        with patch.object(fetch_de, "fetch_url", return_value=PAGE_THREE_DRAWS):
            with self.assertRaisesRegex(ValueError, "requested 2024"):
                fetch_de.fetch_year(2024, set())

    def test_one_corrupt_draw_aborts_entire_source(self):
        with patch.object(fetch_de, "fetch_url", return_value=VALID_ROW_1 + ROW_INVALID_RANGE):
            with self.assertRaisesRegex(ValueError, "out of range"):
                fetch_de.fetch_year(2025, set())

    def test_stale_archive_resumes_at_last_stored_year(self):
        with patch.object(fetch_de, "load_existing_dates", return_value={"2022-12-31"}), \
             patch.object(fetch_de, "fetch_year", return_value=[]) as fetch_year, \
             patch.object(fetch_de, "date", wraps=date) as clock:
            clock.today.return_value = date(2026, 9, 20)
            fetch_de.fetch_new_draws()
        self.assertEqual([call.args[0] for call in fetch_year.call_args_list], [2022, 2023, 2024, 2025, 2026])


class TestMain(unittest.TestCase):
    def test_commit_retries_pending_changes_without_new_draws(self):
        with patch.object(fetch_de, "fetch_new_draws", return_value=[]), \
             patch.object(fetch_de, "git_commit", return_value=False) as commit, \
             patch.object(Path, "exists", return_value=True), \
             patch.object(sys, "argv", ["fetch_lotto_de_6aus49.py", "--commit"]):
            self.assertEqual(fetch_de.main(), 0)
        commit.assert_called_once()

    def test_commit_failure_is_reported(self):
        with patch.object(fetch_de, "fetch_new_draws", return_value=[]), \
             patch.object(fetch_de, "git_commit", side_effect=OSError("git failure")), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(sys, "argv", ["fetch_lotto_de_6aus49.py", "--commit"]), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fetch_de.main(), -1)

    def test_write_failure_is_reported(self):
        draw = Draw("2026-01-03", 1, 4, 15, 16, 22, 38, 5)
        with patch.object(fetch_de, "fetch_new_draws", return_value=[draw]), \
             patch.object(fetch_de, "write_draws", side_effect=OSError("disk full")), \
             patch.object(sys, "argv", ["fetch_lotto_de_6aus49.py"]), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fetch_de.main(), -1)

    def test_unknown_option_is_rejected(self):
        with patch.object(sys, "argv", ["fetch_lotto_de_6aus49.py", "--inti"]), \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exc:
                fetch_de.main()
        self.assertEqual(exc.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
