"""
Unit tests for fetch_lotto_at_6aus45.py

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

import fetch_lotto_at_6aus45 as fetch_at
from fetch_lotto_at_6aus45 import Draw


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

YEARLY_CSV = (
    "Datum;Reihenfolge;Zahl1;Zahl2;Zahl3;Zahl4;Zahl5;Zahl6;ZZ;Zusatzzahl;"
    "Rang_1_5;Anzahl_1_5;a_1_5;Quote_1_5\n"
    "04.01.;aufsteigend;1;4;15;16;22;38;ZZ;11;6er;1;€;1.200.000,00\n"
    "04.01.;;;;;;;;;;4er;3.027;€;62,70\n"          # prize-only row, must be skipped
    "07.01.;aufsteigend;4;5;16;21;35;45;ZZ;33;6er;JP;;690.345,70\n"
    "07.01.;;;;;;;;;;4er;2.907;€;56,50\n"
)

HISTORICAL_CSV = (
    ";;;;\n"
    "2010 Lotto - Beträge in EUR;;;;\n"
    ";;;;\n"
    " Datum;;Reihenfolge;Zahlen;;;;;\n"
    "Mi;08.9.;aufsteigend;4;30;31;32;34;38;Zz;33;6er;JP;;877.301,90\n"
    ";;gezogen;32;30;38;4;34;31;Zz;33;4er;4.161\n"  # skipped
    "So;12.9.;aufsteigend;1;9;19;34;39;43;Zz;8;6er;1;;2.205.765,30\n"
    "2011 Lotto - Beträge in EUR;;;;\n"
    "Mi;05.1.;aufsteigend;2;7;12;20;28;44;Zz;15;6er;1;;1.400.000,00\n"
)

# Format B: weekday has trailing ".", no "aufsteigend" column. The older source
# spans 1986-2010, but only sections from 2000 onwards belong in the archive.
HISTORICAL_CSV_FORMAT_B = (
    ";;;;\n"
    "1986 Lotto - Beträge in ATS;;;;\n"
    ";;;;\n"
    "So.;07.09.;1;20;22;24;27;40;Zz:;12;1;à;6.542.159,00\n"
    "So.;14.09.;9;10;20;30;32;36;Zz:;25;3;à;2.290.274,00\n"
    "1999 Lotto - Beträge in ATS;;;;\n"
    "Fr.;31.12.;bad;older;source;data\n"
    "2000 Lotto - Beträge in ATS;;;;\n"
    "Sa.;01.01.;1;20;22;24;27;40;Zz:;12;1;à;6.542.159,00\n"
    "Di.;29.02.;9;10;20;30;32;36;Zz:;25;3;à;2.290.274,00\n"
    "2001 Lotto - Beträge in ATS;;;;\n"
    "So.;04.01.;3;8;15;22;31;44;Zz:;7;1;à;5.000.000,00\n"
)


# ---------------------------------------------------------------------------
# parse_yearly_file
# ---------------------------------------------------------------------------

class TestParseYearlyFile(unittest.TestCase):
    def setUp(self):
        self.draws = fetch_at.parse_yearly_file(YEARLY_CSV, 2026)

    def test_returns_two_draws(self):
        self.assertEqual(len(self.draws), 2)

    def test_first_draw_date(self):
        self.assertEqual(self.draws[0].date, "2026-01-04")

    def test_first_draw_numbers(self):
        d = self.draws[0]
        self.assertEqual((d.n1, d.n2, d.n3, d.n4, d.n5, d.n6), (1, 4, 15, 16, 22, 38))

    def test_first_draw_zusatzzahl(self):
        self.assertEqual(self.draws[0].zusatzzahl, 11)

    def test_prize_only_rows_skipped(self):
        self.assertEqual(len(self.draws), 2)

    def test_empty_content_returns_empty_list(self):
        self.assertEqual(fetch_at.parse_yearly_file("", 2026), [])

    def test_strict_parsing_rejects_partial_corruption(self):
        with self.assertRaisesRegex(ValueError, "invalid numbers"):
            fetch_at.parse_yearly_file(YEARLY_CSV.replace("1;4;15;", "bad;4;15;"), 2026, strict=True)

    def test_missing_header_rejected_by_import(self):
        with self.assertRaisesRegex(ValueError, "missing.*header"):
            fetch_at.parse_yearly_file("<html>Service unavailable</html>", 2026, strict=True)

    def test_bom_header_is_supported(self):
        self.assertEqual(fetch_at.parse_yearly_file("\ufeff" + YEARLY_CSV, 2026), self.draws)

    def test_requested_year_before_2000_is_rejected(self):
        for strict in (False, True):
            with self.subTest(strict=strict):
                with self.assertRaisesRegex(ValueError, "1999.*archive start 2000"):
                    fetch_at.parse_yearly_file(YEARLY_CSV, 1999, strict=strict)

    def test_boundary_year_and_leap_day_are_preserved(self):
        content = YEARLY_CSV.replace("04.01.", "01.01.").replace("07.01.", "29.02.")
        draws = fetch_at.parse_yearly_file(content, 2000, strict=True)
        self.assertEqual([draw.date for draw in draws], ["2000-01-01", "2000-02-29"])


# ---------------------------------------------------------------------------
# parse_historical_file
# ---------------------------------------------------------------------------

class TestParseHistoricalFile(unittest.TestCase):
    def setUp(self):
        self.draws = fetch_at.parse_historical_file(HISTORICAL_CSV)

    def test_returns_three_draws(self):
        self.assertEqual(len(self.draws), 3)

    def test_year_parsed_from_header_2010(self):
        self.assertEqual(self.draws[0].date, "2010-09-08")

    def test_year_parsed_from_header_2011(self):
        self.assertEqual(self.draws[2].date, "2011-01-05")

    def test_numbers_correct(self):
        d = self.draws[0]
        self.assertEqual((d.n1, d.n2, d.n3, d.n4, d.n5, d.n6), (4, 30, 31, 32, 34, 38))
        self.assertEqual(d.zusatzzahl, 33)

    def test_gezogen_rows_skipped(self):
        self.assertEqual(len(self.draws), 3)

    def test_no_year_header_returns_empty(self):
        content = "Mi;08.9.;aufsteigend;4;30;31;32;34;38;Zz;33\n"
        self.assertEqual(fetch_at.parse_historical_file(content), [])

    def test_eligible_malformed_rows_still_fail_strict_validation(self):
        for content in (
            HISTORICAL_CSV.replace("aufsteigend;4;30;", "aufsteigend;bad;30;"),
            HISTORICAL_CSV.replace("Mi;08.9.;", "Mi;31.9.;"),
        ):
            with self.subTest(content=content):
                with self.assertRaisesRegex(ValueError, "invalid"):
                    fetch_at.parse_historical_file(content, strict=True)


class TestParseHistoricalFileFormatB(unittest.TestCase):
    """Tests for the 1986-2010 format (no 'aufsteigend' column, weekday with '.')."""

    def setUp(self):
        self.draws = fetch_at.parse_historical_file(HISTORICAL_CSV_FORMAT_B, strict=True)

    def test_returns_three_draws(self):
        self.assertEqual(len(self.draws), 3)

    def test_first_draw_date(self):
        self.assertEqual(self.draws[0].date, "2000-01-01")

    def test_first_draw_numbers(self):
        d = self.draws[0]
        self.assertEqual((d.n1, d.n2, d.n3, d.n4, d.n5, d.n6), (1, 20, 22, 24, 27, 40))

    def test_first_draw_zusatzzahl(self):
        self.assertEqual(self.draws[0].zusatzzahl, 12)

    def test_year_boundary_parsed(self):
        self.assertEqual(self.draws[2].date, "2001-01-04")

    def test_leap_day_in_boundary_year_is_preserved(self):
        self.assertEqual(self.draws[1].date, "2000-02-29")

    def test_old_sections_are_skipped_in_diagnostic_and_strict_modes(self):
        for strict in (False, True):
            with self.subTest(strict=strict), contextlib.redirect_stderr(io.StringIO()) as warnings:
                draws = fetch_at.parse_historical_file(HISTORICAL_CSV_FORMAT_B, strict=strict)
                self.assertEqual(draws, self.draws)
                self.assertTrue(all(draw.date >= "2000-01-01" for draw in draws))
                self.assertEqual(warnings.getvalue(), "")

    def test_out_of_order_year_sections_do_not_stop_parsing(self):
        content = HISTORICAL_CSV_FORMAT_B + (
            "1999 Lotto - Beträge in ATS;;;;\n"
            "Fr.;31.12.;bad;older;source;data\n"
            "2002 Lotto - Beträge in EUR;;;;\n"
            "Mi.;02.01.;1;2;3;4;5;6;Zz:;7\n"
        )
        draws = fetch_at.parse_historical_file(content, strict=True)
        self.assertEqual([draw.date for draw in draws], [
            "2000-01-01", "2000-02-29", "2001-01-04", "2002-01-02",
        ])

    def test_eligible_malformed_format_b_row_is_rejected(self):
        content = HISTORICAL_CSV_FORMAT_B.replace("Sa.;01.01.;1;20;", "Sa.;01.01.;bad;20;")
        with self.assertRaisesRegex(ValueError, "invalid numbers"):
            fetch_at.parse_historical_file(content, strict=True)

    def test_cancellation_and_postponement_notices_are_not_draws(self):
        # Keep notice recognition covered within the supported year range,
        # using the official notice formats with synthetic eligible dates.
        notices = (
            "2000 Lotto - Beträge in ATS;;;;\n"
            "So.;28.12.;Ziehung wurde auf den 1.1.2001 verschoben;;;;;;;;\n"
            "2001 Lotto - Beträge in ATS;;;;\n"
            "Mi.;23.12.;e n t f a l l e n ;;;;;;;;\n"
        )
        self.assertEqual(fetch_at.parse_historical_file(
            notices + HISTORICAL_CSV_FORMAT_B, strict=True,
        ), self.draws)


# ---------------------------------------------------------------------------
# validate_draw
# ---------------------------------------------------------------------------

class TestValidateDraw(unittest.TestCase):
    def _make(self, numbers=(1, 2, 3, 4, 5, 6), zusatzzahl=7):
        return Draw("2025-01-01", *numbers, zusatzzahl)

    def test_valid_draw_passes(self):
        valid, reason = fetch_at.validate_draw(self._make())
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_boundary_numbers_pass(self):
        valid, _ = fetch_at.validate_draw(self._make(numbers=(1, 2, 3, 4, 5, 45)))
        self.assertTrue(valid)

    def test_duplicate_numbers_fail(self):
        valid, reason = fetch_at.validate_draw(self._make(numbers=(1, 1, 3, 4, 5, 6)))
        self.assertFalse(valid)
        self.assertIn("duplicate", reason)

    def test_number_zero_fails(self):
        valid, reason = fetch_at.validate_draw(self._make(numbers=(0, 2, 3, 4, 5, 6)))
        self.assertFalse(valid)
        self.assertIn("out of range", reason)

    def test_number_46_fails(self):
        valid, reason = fetch_at.validate_draw(self._make(numbers=(1, 2, 3, 4, 5, 46)))
        self.assertFalse(valid)
        self.assertIn("out of range", reason)

    def test_zusatzzahl_zero_fails(self):
        valid, reason = fetch_at.validate_draw(self._make(zusatzzahl=0))
        self.assertFalse(valid)
        self.assertIn("zusatzzahl", reason)

    def test_zusatzzahl_46_fails(self):
        valid, reason = fetch_at.validate_draw(self._make(zusatzzahl=46))
        self.assertFalse(valid)
        self.assertIn("zusatzzahl", reason)

    def test_zusatzzahl_must_not_repeat_main_number(self):
        valid, reason = fetch_at.validate_draw(self._make(zusatzzahl=6))
        self.assertFalse(valid)
        self.assertIn("duplicates a main", reason)

    def test_invalid_calendar_date_fails(self):
        self.assertFalse(fetch_at.validate_draw(self._make()._replace(date="2025-02-30"))[0])

    def test_date_before_2000_fails(self):
        valid, reason = fetch_at.validate_draw(self._make()._replace(date="1999-12-31"))
        self.assertFalse(valid)
        self.assertIn("2000-01-01", reason)

    def test_first_supported_date_and_leap_day_pass(self):
        for draw_date in ("2000-01-01", "2000-02-29"):
            with self.subTest(date=draw_date):
                self.assertEqual(fetch_at.validate_draw(self._make()._replace(date=draw_date)), (True, ""))


# ---------------------------------------------------------------------------
# parse_date_str
# ---------------------------------------------------------------------------

class TestParseDateStr(unittest.TestCase):
    def test_standard_format(self):
        self.assertEqual(fetch_at.parse_date_str("04.01.", 2026), date(2026, 1, 4))

    def test_single_digit_month(self):
        self.assertEqual(fetch_at.parse_date_str("08.9.", 2010), date(2010, 9, 8))

    def test_invalid_returns_none(self):
        self.assertIsNone(fetch_at.parse_date_str("not-a-date", 2026))

    def test_empty_returns_none(self):
        self.assertIsNone(fetch_at.parse_date_str("", 2026))

    def test_explicit_wrong_year_is_rejected(self):
        self.assertIsNone(fetch_at.parse_date_str("04.01.2025", 2026))

    def test_explicit_matching_year_is_supported(self):
        self.assertEqual(fetch_at.parse_date_str("04.01.2026", 2026), date(2026, 1, 4))

    def test_impossible_date_is_rejected(self):
        self.assertIsNone(fetch_at.parse_date_str("30.02.", 2026))


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------

class TestCsvIO(unittest.TestCase):
    def _draw(self, date="2026-01-04", numbers=(1, 4, 15, 16, 22, 38), zusatzzahl=11):
        return Draw(date, *numbers, zusatzzahl)

    def test_load_existing_draws_missing_file_returns_empty(self):
        self.assertEqual(fetch_at.load_existing_draws(Path("/nonexistent/path.csv")), [])

    def test_load_existing_dates_missing_file_returns_empty(self):
        self.assertEqual(fetch_at.load_existing_dates(Path("/nonexistent/path.csv")), set())

    def test_write_and_reload_roundtrip(self):
        import tempfile, pathlib
        draw = self._draw()
        with tempfile.TemporaryDirectory() as tmp:
            real_path = pathlib.Path(tmp) / "results.csv"
            original = fetch_at.RESULTS_CSV
            fetch_at.RESULTS_CSV = real_path
            try:
                fetch_at.write_draws([draw])
                loaded = fetch_at.load_existing_draws(real_path)
            finally:
                fetch_at.RESULTS_CSV = original

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].date, "2026-01-04")
        self.assertEqual(loaded[0].n1, 1)
        self.assertEqual(loaded[0].zusatzzahl, 11)

    def test_write_draws_merges_with_existing(self):
        """Writing new draws must not overwrite draws already in the file."""
        import tempfile, pathlib
        draw1 = self._draw(date="2026-01-04")
        draw2 = self._draw(date="2026-01-07", numbers=(4, 5, 16, 21, 35, 45), zusatzzahl=33)
        with tempfile.TemporaryDirectory() as tmp:
            real_path = pathlib.Path(tmp) / "results.csv"
            original = fetch_at.RESULTS_CSV
            fetch_at.RESULTS_CSV = real_path
            try:
                fetch_at.write_draws([draw1])
                fetch_at.write_draws([draw2])
                loaded = fetch_at.load_existing_draws(real_path)
            finally:
                fetch_at.RESULTS_CSV = original

        self.assertEqual(len(loaded), 2)

    def test_write_draws_sorted_by_date(self):
        """Draws must be written in chronological order regardless of input order."""
        import tempfile, pathlib
        draw_late = self._draw(date="2026-01-07")
        draw_early = self._draw(date="2026-01-04", numbers=(1, 2, 3, 4, 5, 6))
        with tempfile.TemporaryDirectory() as tmp:
            real_path = pathlib.Path(tmp) / "results.csv"
            original = fetch_at.RESULTS_CSV
            fetch_at.RESULTS_CSV = real_path
            try:
                fetch_at.write_draws([draw_late, draw_early])
                loaded = fetch_at.load_existing_draws(real_path)
            finally:
                fetch_at.RESULTS_CSV = original

        self.assertEqual(loaded[0].date, "2026-01-04")
        self.assertEqual(loaded[1].date, "2026-01-07")

    def test_write_draws_overwrites_on_date_collision(self):
        """Writing a draw for an existing date replaces the old draw."""
        import tempfile, pathlib
        original_draw = self._draw(date="2026-01-04", numbers=(1, 2, 3, 4, 5, 6))
        updated_draw = self._draw(date="2026-01-04", numbers=(4, 5, 16, 21, 35, 45))
        with tempfile.TemporaryDirectory() as tmp:
            real_path = pathlib.Path(tmp) / "results.csv"
            original = fetch_at.RESULTS_CSV
            fetch_at.RESULTS_CSV = real_path
            try:
                fetch_at.write_draws([original_draw])
                fetch_at.write_draws([updated_draw])
                loaded = fetch_at.load_existing_draws(real_path)
            finally:
                fetch_at.RESULTS_CSV = original

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].n1, 4)

    def test_old_incoming_draw_does_not_change_existing_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "results.csv"
            with patch.object(fetch_at, "RESULTS_CSV", csv_path):
                fetch_at.write_draws([self._draw(date="2000-01-01")])
                before = csv_path.read_bytes()
                with self.assertRaisesRegex(ValueError, "1999-12-31.*2000-01-01"):
                    fetch_at.write_draws([
                        self._draw(date="2000-02-29"), self._draw(date="1999-12-31"),
                    ])
                self.assertEqual(csv_path.read_bytes(), before)

    def test_old_existing_draw_is_rejected_and_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "results.csv"
            csv_path.write_text(
                ",".join(Draw._fields) + "\n1999-12-31,1,4,15,16,22,38,11\n",
                encoding="utf-8",
            )
            before = csv_path.read_bytes()
            with patch.object(fetch_at, "RESULTS_CSV", csv_path):
                with self.assertRaisesRegex(ValueError, "1999-12-31.*2000-01-01"):
                    fetch_at.load_existing_dates(csv_path)
                with self.assertRaisesRegex(ValueError, "1999-12-31.*2000-01-01"):
                    fetch_at.write_draws([self._draw(date="2000-01-01")])
            self.assertEqual(csv_path.read_bytes(), before)


# ---------------------------------------------------------------------------
# fetch_new_draws deduplication
# ---------------------------------------------------------------------------

class TestFetchNewDraws(unittest.TestCase):
    def test_full_init_bootstrap_and_stale_recovery_only_import_since_2000(self):
        def source(url):
            if url == fetch_at.HISTORICAL_URLS[0]:
                return HISTORICAL_CSV_FORMAT_B
            if url == fetch_at.HISTORICAL_URLS[1]:
                return HISTORICAL_CSV
            return YEARLY_CSV

        for init, existing_dates in (
            (True, {"2026-01-04"}),
            (False, set()),
            (False, {"2001-01-04"}),
        ):
            with self.subTest(init=init, existing_dates=existing_dates):
                with patch.object(fetch_at, "load_existing_dates", return_value=existing_dates), \
                     patch.object(fetch_at, "fetch_url", side_effect=source) as fetch, \
                     patch.object(fetch_at, "date", wraps=date) as clock:
                    clock.today.return_value = date(2026, 9, 20)
                    draws = fetch_at.fetch_new_draws(init=init)
                dates = {draw.date for draw in draws}
                self.assertIn("2000-01-01", dates)
                self.assertIn("2000-02-29", dates)
                self.assertIn("2026-01-07", dates)
                self.assertTrue(all(draw_date >= "2000-01-01" for draw_date in dates))
                self.assertFalse(dates & existing_dates)
                self.assertEqual([call.args[0] for call in fetch.call_args_list], [
                    *fetch_at.HISTORICAL_URLS,
                    *(fetch_at.YEARLY_BASE_URL.format(year=year) for year in range(2018, 2027)),
                ])

    def test_existing_dates_are_excluded(self):
        """Draws whose date is already in results.csv must not be returned."""
        # YEARLY_CSV has draws for 04.01. and 07.01. of the given year.
        # fetch_new_draws fetches current year and previous year, so with year=2026
        # we get dates 2025-01-04, 2025-01-07, 2026-01-04, 2026-01-07.
        existing_dates = {"2026-01-04", "2026-01-07"}

        with patch("fetch_lotto_at_6aus45.load_existing_dates",
                   return_value=existing_dates), \
             patch("fetch_lotto_at_6aus45.fetch_url", return_value=YEARLY_CSV), \
             patch.object(fetch_at, "date", wraps=date) as clock:
            clock.today.return_value = date(2026, 9, 20)
            draws = fetch_at.fetch_new_draws(init=False)

        self.assertFalse(any(d.date in existing_dates for d in draws))

    def test_stale_archive_fetches_every_intervening_year(self):
        with patch.object(fetch_at, "load_existing_dates", return_value={"2022-12-28"}), \
             patch.object(fetch_at, "fetch_url", return_value=YEARLY_CSV) as fetch, \
             patch.object(fetch_at, "date", wraps=date) as clock:
            clock.today.return_value = date(2026, 9, 20)
            fetch_at.fetch_new_draws()
        self.assertEqual([call.args[0] for call in fetch.call_args_list], [
            fetch_at.YEARLY_BASE_URL.format(year=year) for year in range(2022, 2027)
        ])

    def test_empty_source_fails(self):
        with patch.object(fetch_at, "load_existing_dates", return_value={"2025-01-01"}), \
             patch.object(fetch_at, "fetch_url", return_value="Datum;Reihenfolge;\n"):
            with self.assertRaisesRegex(ValueError, "no valid draws"):
                fetch_at.fetch_new_draws()

    def test_failed_download_does_not_report_success(self):
        with patch.object(fetch_at, "load_existing_dates", return_value={"2025-01-01"}), \
             patch.object(fetch_at, "fetch_url", side_effect=fetch_at.HTTPError("HTTP failure")), \
             patch.object(sys, "argv", ["fetch_lotto_at_6aus45.py"]), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fetch_at.main(), -1)


class TestMain(unittest.TestCase):
    def test_write_failure_is_reported(self):
        draw = Draw("2026-01-04", 1, 4, 15, 16, 22, 38, 11)
        with patch.object(fetch_at, "fetch_new_draws", return_value=[draw]), \
             patch.object(fetch_at, "write_draws", side_effect=OSError("disk full")), \
             patch.object(sys, "argv", ["fetch_lotto_at_6aus45.py"]), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fetch_at.main(), -1)

    def test_commit_retries_pending_changes_without_new_draws(self):
        with patch.object(fetch_at, "fetch_new_draws", return_value=[]), \
             patch.object(fetch_at, "git_commit", return_value=False) as commit, \
             patch.object(Path, "exists", return_value=True), \
             patch.object(sys, "argv", ["fetch_lotto_at_6aus45.py", "--commit"]):
            self.assertEqual(fetch_at.main(), 0)
        commit.assert_called_once()

    def test_unknown_option_is_rejected(self):
        with patch.object(sys, "argv", ["fetch_lotto_at_6aus45.py", "--inti"]), \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exc:
                fetch_at.main()
        self.assertEqual(exc.exception.code, 2)

    def test_commit_failure_is_reported(self):
        with patch.object(fetch_at, "fetch_new_draws", return_value=[]), \
             patch.object(fetch_at, "git_commit", side_effect=OSError("git failure")), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(sys, "argv", ["fetch_lotto_at_6aus45.py", "--commit"]), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fetch_at.main(), -1)


if __name__ == "__main__":
    unittest.main()
