"""
Unit tests for fetch_euromillions.py

All tests are offline — no network requests are made.
"""

import contextlib
import csv
import io
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import fetch_euromillions as fetch_eu
from fetch_euromillions import Draw


# ---------------------------------------------------------------------------
# CSV fixtures — yearly format (2017–present, semicolon-delimited)
# ---------------------------------------------------------------------------

# Header + two draw rows + one prize-detail row (empty col[0])
YEARLY_VALID = (
    "Ziehungstag;Zahl1;Zahl2;Zahl3;Zahl4;Zahl5;Stern1;Stern2;Rang;Zahlen;Sterne;Europa;Österreich;Quoten;\n"
    "Fr. 03.01.2025;3;19;29;35;37;1;9;1;5;2;JP;JP;29139978,90;\n"
    ";;;;;;;;;2;5;2;100000,00;60000,00;\n"   # prize row — no date
    "Di. 07.01.2025;12;17;27;44;50;4;11;1;5;2;JP;JP;31000000,00;\n"
)

YEARLY_EMPTY = (
    "Ziehungstag;Zahl1;Zahl2;Zahl3;Zahl4;Zahl5;Stern1;Stern2;\n"
)

YEARLY_INVALID_RANGE = (
    "Ziehungstag;Zahl1;Zahl2;Zahl3;Zahl4;Zahl5;Stern1;Stern2;\n"
    "Fr. 10.01.2025;0;2;3;4;5;1;2;\n"   # n1=0 — out of range
)

YEARLY_INVALID_STAR = (
    "Ziehungstag;Zahl1;Zahl2;Zahl3;Zahl4;Zahl5;Stern1;Stern2;\n"
    "Fr. 10.01.2025;1;2;3;4;5;1;13;\n"  # s2=13 — out of range
)

YEARLY_DUPLICATE_MAIN = (
    "Ziehungstag;Zahl1;Zahl2;Zahl3;Zahl4;Zahl5;Stern1;Stern2;\n"
    "Fr. 10.01.2025;1;1;3;4;5;1;2;\n"   # n1=n2=1
)

YEARLY_DUPLICATE_STAR = (
    "Ziehungstag;Zahl1;Zahl2;Zahl3;Zahl4;Zahl5;Stern1;Stern2;\n"
    "Fr. 10.01.2025;1;2;3;4;5;3;3;\n"   # s1=s2=3
)


# ---------------------------------------------------------------------------
# CSV fixtures — historical format (2004–2016, sideways, semicolon-delimited)
# ---------------------------------------------------------------------------

# Two draws per block: date in Runde row, numbers in the next row
HIST_TWO_DRAWS = (
    ";Ergebnisse:;;;;;;;;Runde;1;13.02.2004;;Ergebnisse:;;;;;;;;Runde;2;20.02.2004;;;\n"
    ";aufsteigende Reihenfolge:;;;;;Sterne;;;;;;;aufsteigende Reihenfolge:;;;;;Sterne;;;;;\n"
    ";16;29;32;36;41;7;9;;;;;;7;13;39;47;50;2;5;;;\n"
)

# Only one draw in block (second Runde absent)
HIST_ONE_DRAW = (
    ";Ergebnisse:;;;;;;;;Runde;1;27.02.2004;;;;;;;;;;;;;;\n"
    ";aufsteigende Reihenfolge:;;;;;Sterne;;;;;;;;;;;;;;\n"
    ";8;11;23;34;48;3;6;;;;;;;;;;;;;;;\n"
)

# Block with invalid number (n1=0 in first draw)
HIST_INVALID = (
    ";Ergebnisse:;;;;;;;;Runde;1;06.03.2004;;Ergebnisse:;;;;;;;;Runde;2;13.03.2004;;;\n"
    ";aufsteigende Reihenfolge:;;;;;Sterne;;;;;;;aufsteigende Reihenfolge:;;;;;Sterne;;;;;\n"
    ";0;2;3;4;5;1;2;;;;;;7;13;39;47;50;2;5;;;\n"  # first draw has n1=0
)


def _historical_block(left_date="", left_values=(), right_date="", right_values=(), *, left_label=True):
    """Build the two independent slots used in the official historical export."""
    header, labels, values = ([""] * 26 for _ in range(3))
    for offset, raw_date, numbers in ((1, left_date, left_values), (13, right_date, right_values)):
        if not raw_date and not numbers:
            continue
        header[offset] = "Ergebnisse:" if offset == 13 or left_label else ""
        header[offset + 10] = raw_date
        labels[offset] = "aufsteigende Reihenfolge:"
        values[offset:offset + len(numbers)] = numbers
    output = io.StringIO()
    csv.writer(output, delimiter=";").writerows([header, labels, values])
    return output.getvalue()


# ---------------------------------------------------------------------------
# parse_yearly_file
# ---------------------------------------------------------------------------

class TestParseYearlyFile(unittest.TestCase):
    def test_returns_two_draws(self):
        draws = fetch_eu.parse_yearly_file(YEARLY_VALID)
        self.assertEqual(len(draws), 2)

    def test_prize_row_skipped(self):
        # YEARLY_VALID has one prize row; only 2 draw rows must survive
        draws = fetch_eu.parse_yearly_file(YEARLY_VALID)
        self.assertEqual(len(draws), 2)

    def test_first_draw_date(self):
        draws = fetch_eu.parse_yearly_file(YEARLY_VALID)
        self.assertEqual(draws[0].date, "2025-01-03")

    def test_first_draw_numbers(self):
        draws = fetch_eu.parse_yearly_file(YEARLY_VALID)
        d = draws[0]
        self.assertEqual((d.n1, d.n2, d.n3, d.n4, d.n5), (3, 19, 29, 35, 37))

    def test_first_draw_stars(self):
        draws = fetch_eu.parse_yearly_file(YEARLY_VALID)
        d = draws[0]
        self.assertEqual((d.s1, d.s2), (1, 9))

    def test_second_draw_date(self):
        draws = fetch_eu.parse_yearly_file(YEARLY_VALID)
        self.assertEqual(draws[1].date, "2025-01-07")

    def test_empty_file_returns_empty_list(self):
        draws = fetch_eu.parse_yearly_file(YEARLY_EMPTY)
        self.assertEqual(draws, [])

    def test_out_of_range_main_number_skipped(self):
        with contextlib.redirect_stderr(io.StringIO()):
            draws = fetch_eu.parse_yearly_file(YEARLY_INVALID_RANGE)
        self.assertEqual(draws, [])

    def test_out_of_range_star_skipped(self):
        with contextlib.redirect_stderr(io.StringIO()):
            draws = fetch_eu.parse_yearly_file(YEARLY_INVALID_STAR)
        self.assertEqual(draws, [])

    def test_duplicate_main_numbers_skipped(self):
        with contextlib.redirect_stderr(io.StringIO()):
            draws = fetch_eu.parse_yearly_file(YEARLY_DUPLICATE_MAIN)
        self.assertEqual(draws, [])

    def test_duplicate_star_numbers_skipped(self):
        with contextlib.redirect_stderr(io.StringIO()):
            draws = fetch_eu.parse_yearly_file(YEARLY_DUPLICATE_STAR)
        self.assertEqual(draws, [])


# ---------------------------------------------------------------------------
# parse_historical_file
# ---------------------------------------------------------------------------

class TestParseHistoricalFile(unittest.TestCase):
    def test_two_draws_parsed(self):
        draws = fetch_eu.parse_historical_file(HIST_TWO_DRAWS)
        self.assertEqual(len(draws), 2)

    def test_first_draw_date(self):
        draws = fetch_eu.parse_historical_file(HIST_TWO_DRAWS)
        self.assertEqual(draws[0].date, "2004-02-13")

    def test_first_draw_numbers(self):
        draws = fetch_eu.parse_historical_file(HIST_TWO_DRAWS)
        d = draws[0]
        self.assertEqual((d.n1, d.n2, d.n3, d.n4, d.n5), (16, 29, 32, 36, 41))

    def test_first_draw_stars(self):
        draws = fetch_eu.parse_historical_file(HIST_TWO_DRAWS)
        d = draws[0]
        self.assertEqual((d.s1, d.s2), (7, 9))

    def test_second_draw_date(self):
        draws = fetch_eu.parse_historical_file(HIST_TWO_DRAWS)
        self.assertEqual(draws[1].date, "2004-02-20")

    def test_second_draw_numbers(self):
        draws = fetch_eu.parse_historical_file(HIST_TWO_DRAWS)
        d = draws[1]
        self.assertEqual((d.n1, d.n2, d.n3, d.n4, d.n5), (7, 13, 39, 47, 50))

    def test_one_draw_block(self):
        draws = fetch_eu.parse_historical_file(HIST_ONE_DRAW)
        self.assertEqual(len(draws), 1)
        self.assertEqual(draws[0].date, "2004-02-27")

    def test_invalid_draw_in_block_skipped(self):
        """First draw is invalid (n1=0), second draw is valid — only second survives."""
        with contextlib.redirect_stderr(io.StringIO()):
            draws = fetch_eu.parse_historical_file(HIST_INVALID)
        self.assertEqual(len(draws), 1)
        self.assertEqual(draws[0].date, "2004-03-13")

    def test_empty_content_returns_empty_list(self):
        draws = fetch_eu.parse_historical_file("")
        self.assertEqual(draws, [])

    def test_right_only_block_keeps_its_own_numbers(self):
        content = _historical_block(right_date="03.01.2014", right_values=(3, 27, 31, 38, 44, 3, 8))
        self.assertEqual(fetch_eu.parse_historical_file(content, strict=True), [
            Draw("2014-01-03", 3, 27, 31, 38, 44, 3, 8),
        ])

    def test_missing_left_label_does_not_drop_either_draw(self):
        content = _historical_block(
            "21.10.2014", (20, 21, 27, 33, 40, 3, 10),
            "24.10.2014", (3, 9, 20, 30, 42, 1, 6), left_label=False,
        )
        self.assertEqual([draw.date for draw in fetch_eu.parse_historical_file(content, strict=True)],
                         ["2014-10-21", "2014-10-24"])

    def test_invalid_left_date_never_shifts_right_date_onto_left_numbers(self):
        content = _historical_block("31.02.2004", (1, 2, 3, 4, 5, 1, 2),
                                    "20.02.2004", (7, 13, 39, 47, 50, 2, 5))
        with contextlib.redirect_stderr(io.StringIO()):
            draws = fetch_eu.parse_historical_file(content)
        self.assertEqual(draws, [Draw("2004-02-20", 7, 13, 39, 47, 50, 2, 5)])

    def test_missing_number_row_cannot_borrow_numbers_from_next_block(self):
        first = _historical_block("13.02.2004", (1, 2, 3, 4, 5, 1, 2))
        truncated = "\n".join(first.splitlines()[:2]) + "\n"
        second = _historical_block("20.02.2004", (7, 13, 39, 47, 50, 2, 5))
        with contextlib.redirect_stderr(io.StringIO()):
            draws = fetch_eu.parse_historical_file(truncated + second)
        self.assertEqual(draws, [Draw("2004-02-20", 7, 13, 39, 47, 50, 2, 5)])

    def test_excel_serial_source_date(self):
        content = _historical_block("38422", (8, 12, 23, 40, 43, 1, 4))
        self.assertEqual(fetch_eu.parse_historical_file(content, strict=True), [
            Draw("2005-03-11", 8, 12, 23, 40, 43, 1, 4),
        ])

    def test_verified_official_source_date_typos_are_repaired(self):
        cases = [
            ("20.11.2099", (5, 9, 28, 43, 47, 2, 9), "2009-11-20"),
            ("26.03.2009", (8, 16, 18, 37, 43, 2, 6), "2010-03-26"),
            ("04.07.2010", (12, 13, 36, 41, 46, 1, 8), "2010-07-02"),
            ("12.09.2012", (6, 15, 22, 37, 44, 2, 4), "2012-09-11"),
            ("16.12.2012", (3, 7, 12, 13, 25, 5, 8), "2014-12-16"),
            ("06.08.2017", (29, 30, 36, 40, 41, 2, 9), "2017-08-04"),
        ]
        for raw_date, numbers, expected_date in cases:
            with self.subTest(raw_date=raw_date):
                self.assertEqual(fetch_eu.parse_historical_file(
                    _historical_block(raw_date, numbers), strict=True,
                ), [Draw(expected_date, *numbers)])

    def test_source_correction_requires_matching_numbers(self):
        content = _historical_block("26.03.2009", (1, 2, 3, 4, 5, 1, 2))
        self.assertEqual(fetch_eu.parse_historical_file(content)[0].date, "2009-03-26")


# ---------------------------------------------------------------------------
# validate_draw
# ---------------------------------------------------------------------------

class TestValidateDraw(unittest.TestCase):
    def _make(self, numbers=(1, 2, 3, 4, 5), stars=(1, 2)):
        return Draw("2025-01-01", *numbers, *stars)

    def test_valid_draw_passes(self):
        valid, reason = fetch_eu.validate_draw(self._make())
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_boundary_numbers_pass(self):
        valid, _ = fetch_eu.validate_draw(self._make(numbers=(1, 2, 3, 4, 50)))
        self.assertTrue(valid)

    def test_boundary_stars_pass(self):
        valid, _ = fetch_eu.validate_draw(self._make(stars=(1, 12)))
        self.assertTrue(valid)

    def test_duplicate_main_numbers_fail(self):
        valid, reason = fetch_eu.validate_draw(self._make(numbers=(1, 1, 3, 4, 5)))
        self.assertFalse(valid)
        self.assertIn("duplicate", reason)

    def test_main_number_zero_fails(self):
        valid, reason = fetch_eu.validate_draw(self._make(numbers=(0, 2, 3, 4, 5)))
        self.assertFalse(valid)
        self.assertIn("out of range", reason)

    def test_main_number_51_fails(self):
        valid, reason = fetch_eu.validate_draw(self._make(numbers=(1, 2, 3, 4, 51)))
        self.assertFalse(valid)
        self.assertIn("out of range", reason)

    def test_duplicate_stars_fail(self):
        valid, reason = fetch_eu.validate_draw(self._make(stars=(5, 5)))
        self.assertFalse(valid)
        self.assertIn("duplicate", reason)

    def test_star_zero_fails(self):
        valid, reason = fetch_eu.validate_draw(self._make(stars=(0, 2)))
        self.assertFalse(valid)
        self.assertIn("out of range", reason)

    def test_star_13_fails(self):
        valid, reason = fetch_eu.validate_draw(self._make(stars=(1, 13)))
        self.assertFalse(valid)
        self.assertIn("out of range", reason)

    def test_impossible_calendar_date_fails(self):
        self.assertFalse(fetch_eu.validate_draw(self._make()._replace(date="2025-02-30"))[0])

    def test_historical_star_pool_boundaries(self):
        for draw_date, star, expected in (
            ("2011-05-06", 10, False), ("2011-05-10", 11, True),
            ("2016-09-23", 12, False), ("2016-09-27", 12, True),
        ):
            with self.subTest(draw_date=draw_date):
                self.assertEqual(fetch_eu.validate_draw(
                    self._make(stars=(1, star))._replace(date=draw_date),
                )[0], expected)


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------

class TestCsvIO(unittest.TestCase):
    def _draw(self, date="2025-01-03", numbers=(3, 19, 29, 35, 37), stars=(1, 9)):
        return Draw(date, *numbers, *stars)

    def test_load_existing_draws_missing_file_returns_empty(self):
        result = fetch_eu.load_existing_draws(Path("/nonexistent/path.csv"))
        self.assertEqual(result, [])

    def test_load_existing_dates_missing_file_returns_empty(self):
        result = fetch_eu.load_existing_dates(Path("/nonexistent/path.csv"))
        self.assertEqual(result, set())

    def test_write_and_reload_roundtrip(self):
        import tempfile, pathlib
        draw = self._draw()
        with tempfile.TemporaryDirectory() as tmp:
            real_path = pathlib.Path(tmp) / "results.csv"
            original = fetch_eu.RESULTS_CSV
            fetch_eu.RESULTS_CSV = real_path
            try:
                fetch_eu.write_draws([draw])
                loaded = fetch_eu.load_existing_draws(real_path)
            finally:
                fetch_eu.RESULTS_CSV = original

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].date, "2025-01-03")
        self.assertEqual(loaded[0].n1, 3)
        self.assertEqual(loaded[0].s1, 1)
        self.assertEqual(loaded[0].s2, 9)

    def test_write_draws_merges_with_existing(self):
        import tempfile, pathlib
        draw1 = self._draw(date="2025-01-03")
        draw2 = self._draw(date="2025-01-07", numbers=(12, 17, 27, 44, 50), stars=(4, 11))
        with tempfile.TemporaryDirectory() as tmp:
            real_path = pathlib.Path(tmp) / "results.csv"
            original = fetch_eu.RESULTS_CSV
            fetch_eu.RESULTS_CSV = real_path
            try:
                fetch_eu.write_draws([draw1])
                fetch_eu.write_draws([draw2])
                loaded = fetch_eu.load_existing_draws(real_path)
            finally:
                fetch_eu.RESULTS_CSV = original

        self.assertEqual(len(loaded), 2)

    def test_write_draws_sorted_by_date(self):
        import tempfile, pathlib
        draw_late = self._draw(date="2025-01-07")
        draw_early = self._draw(date="2025-01-03", numbers=(1, 2, 3, 4, 5))
        with tempfile.TemporaryDirectory() as tmp:
            real_path = pathlib.Path(tmp) / "results.csv"
            original = fetch_eu.RESULTS_CSV
            fetch_eu.RESULTS_CSV = real_path
            try:
                fetch_eu.write_draws([draw_late, draw_early])
                loaded = fetch_eu.load_existing_draws(real_path)
            finally:
                fetch_eu.RESULTS_CSV = original

        self.assertEqual(loaded[0].date, "2025-01-03")
        self.assertEqual(loaded[1].date, "2025-01-07")

    def test_write_draws_overwrites_on_date_collision(self):
        """Writing a draw for an existing date replaces the old draw."""
        import tempfile, pathlib
        original_draw = self._draw(date="2025-01-03", numbers=(1, 2, 3, 4, 5))
        updated_draw = self._draw(date="2025-01-03", numbers=(3, 19, 29, 35, 37))
        with tempfile.TemporaryDirectory() as tmp:
            real_path = pathlib.Path(tmp) / "results.csv"
            original = fetch_eu.RESULTS_CSV
            fetch_eu.RESULTS_CSV = real_path
            try:
                fetch_eu.write_draws([original_draw])
                fetch_eu.write_draws([updated_draw])
                loaded = fetch_eu.load_existing_draws(real_path)
            finally:
                fetch_eu.RESULTS_CSV = original

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].n1, 3)
        self.assertEqual(loaded[0].n2, 19)


# ---------------------------------------------------------------------------
# fetch_new_draws deduplication
# ---------------------------------------------------------------------------

class TestFetchNewDraws(unittest.TestCase):
    def test_existing_dates_are_excluded(self):
        """Draws whose date is already in results.csv must not be returned."""
        # YEARLY_VALID has draws for 2025-01-03 and 2025-01-07.
        # fetch_new_draws (init=False) fetches current and previous year.
        pre_existing = {"2025-01-03"}

        with patch("fetch_euromillions.load_existing_dates",
                   return_value=set(pre_existing)), \
             patch("fetch_euromillions.fetch_url", side_effect=[
                 YEARLY_VALID,
                 YEARLY_VALID.replace("03.01.2025", "02.01.2026").replace("07.01.2025", "06.01.2026"),
             ]), patch("fetch_euromillions.date", wraps=date) as clock:
            clock.today.return_value = date(2026, 9, 20)
            draws = fetch_eu.fetch_new_draws(init=False)

        self.assertFalse(any(d.date in pre_existing for d in draws))
        self.assertEqual(len(draws), 3)

    def test_malformed_html_response_fails(self):
        with patch.object(fetch_eu, "load_existing_dates", return_value={"2025-01-03"}), \
             patch.object(fetch_eu, "fetch_url", return_value="<html>Service unavailable</html>"):
            with self.assertRaisesRegex(ValueError, "missing.*header"):
                fetch_eu.fetch_new_draws()

    def test_empty_source_fails(self):
        with patch.object(fetch_eu, "load_existing_dates", return_value={"2025-01-03"}), \
             patch.object(fetch_eu, "fetch_url", return_value=YEARLY_EMPTY):
            with self.assertRaisesRegex(ValueError, "no valid draws"):
                fetch_eu.fetch_new_draws()

    def test_partial_source_corruption_fails(self):
        with self.assertRaisesRegex(ValueError, "invalid draw date"):
            fetch_eu.parse_yearly_file(YEARLY_VALID.replace("03.01.2025", "30.02.2025"), strict=True)

    def test_failed_download_is_not_reported_as_success(self):
        with patch.object(fetch_eu, "load_existing_dates", return_value={"2025-01-03"}), \
             patch.object(fetch_eu, "fetch_url", side_effect=fetch_eu.HTTPError("HTTP failure")), \
             patch.object(sys, "argv", ["fetch_euromillions.py"]), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fetch_eu.main(), -1)


class TestMain(unittest.TestCase):
    def test_commit_retries_pending_changes_without_new_draws(self):
        with patch.object(fetch_eu, "fetch_new_draws", return_value=[]), \
             patch.object(fetch_eu, "git_commit", return_value=False) as commit, \
             patch.object(Path, "exists", return_value=True), \
             patch.object(sys, "argv", ["fetch_euromillions.py", "--commit"]):
            self.assertEqual(fetch_eu.main(), 0)
        commit.assert_called_once()

    def test_commit_failure_is_reported(self):
        with patch.object(fetch_eu, "fetch_new_draws", return_value=[]), \
             patch.object(fetch_eu, "git_commit", side_effect=OSError("git failure")), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(sys, "argv", ["fetch_euromillions.py", "--commit"]), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fetch_eu.main(), -1)

    def test_write_failure_is_reported(self):
        draw = Draw("2026-01-02", 1, 4, 15, 16, 22, 1, 5)
        with patch.object(fetch_eu, "fetch_new_draws", return_value=[draw]), \
             patch.object(fetch_eu, "write_draws", side_effect=OSError("disk full")), \
             patch.object(sys, "argv", ["fetch_euromillions.py"]), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(fetch_eu.main(), -1)

    def test_unknown_option_is_rejected(self):
        with patch.object(sys, "argv", ["fetch_euromillions.py", "--inti"]), \
             contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exc:
                fetch_eu.main()
        self.assertEqual(exc.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
