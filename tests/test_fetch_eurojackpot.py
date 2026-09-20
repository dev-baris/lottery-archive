"""Offline regressions using an actual 2012 archive fragment and edge cases."""

import contextlib
import io
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import fetch_eurojackpot as ej

FIXTURE = Path(__file__).parent / "fixtures" / "eurojackpot_2012.html"
FIRST = ej.Draw("2012-03-23", 5, 8, 21, 37, 46, 6, 8)


def one_row(day="02.01.2026", numbers=(10, 15, 29, 34, 38), euros=(2, 9), year=2026):
    return (
        f'<div id="gewinnzahlen"><h3>Gewinnzahlen aus dem Jahr {year}</h3>'
        '<div class="zahlen_rahmen">'
        f'<time class="zahlenarchiv_datum" datetime="2026-02-01">{day}</time>'
        + "".join(f'<div class="zahlenarchiv_zahl">{n}</div>' for n in numbers)
        + "".join(f'<div class="zahlenarchiv_zz">{n}</div>' for n in euros)
        + "</div></div>"
    )


class TestArchiveParsing(unittest.TestCase):
    def setUp(self):
        self.html = FIXTURE.read_text(encoding="utf-8")

    def parse(self, html=None):
        return ej.parse_year(self.html if html is None else html, 2012, reference_date=date(2026, 9, 20))

    def test_real_first_year_has_complete_41_draws(self):
        draws = self.parse()
        self.assertEqual(len(draws), 41)
        self.assertEqual(draws[0], FIRST)
        self.assertEqual(draws[-1].date, "2012-12-28")

    def test_visible_date_wins_over_incorrect_datetime_attribute(self):
        self.assertIn('datetime="2012-23-03"', self.html)
        self.assertEqual(self.parse()[0].date, "2012-03-23")
        draws = ej.parse_year(one_row(), 2026, reference_date=date(2026, 1, 3))
        self.assertEqual(draws[0].date, "2026-01-02")

    def test_ignores_unrelated_numbers_outside_archive(self):
        extra = '<div class="zahlenarchiv_zahl">999</div>'
        self.assertEqual(self.parse(extra + self.html + extra), self.parse())

    def test_missing_draw_fails_instead_of_returning_partial_year(self):
        soup = BeautifulSoup(self.html, "lxml")
        soup.select(".zahlen_rahmen")[12].decompose()
        with self.assertRaisesRegex(ValueError, "incomplete.*1 missing"):
            self.parse(str(soup))

    def test_missing_container_or_wrong_year_heading_fails(self):
        for html in ("<html>Maintenance</html>", self.html.replace("Jahr 2012", "Jahr 2026")):
            with self.subTest(html=html[:40]), self.assertRaises(ValueError):
                self.parse(html)

    def test_duplicate_draw_fails(self):
        soup = BeautifulSoup(self.html, "lxml")
        soup.select_one("#gewinnzahlen").append(soup.select(".zahlen_rahmen")[1].__copy__())
        with self.assertRaisesRegex(ValueError, "duplicate draw date"):
            self.parse(str(soup))

    def test_malformed_number_row_fails(self):
        soup = BeautifulSoup(self.html, "lxml")
        soup.select_one(".zahlenarchiv_zz").decompose()
        with self.assertRaisesRegex(ValueError, "malformed archive row"):
            self.parse(str(soup))

    def test_impossible_date_fails(self):
        with self.assertRaisesRegex(ValueError, "invalid calendar date"):
            self.parse(self.html.replace(">23.03.2012<", ">31.02.2012<"))

    def test_wrong_year_row_fails(self):
        with self.assertRaisesRegex(ValueError, "unexpected draw year"):
            self.parse(self.html.replace(">23.03.2012<", ">23.03.2013<"))

    def test_future_draw_fails(self):
        with self.assertRaisesRegex(ValueError, "future draw"):
            ej.parse_year(one_row(), 2026, reference_date=date(2026, 1, 1))

    def test_current_draw_day_may_be_awaiting_publication(self):
        empty = '<div id="gewinnzahlen"><h3>Gewinnzahlen aus dem Jahr 2026</h3></div>'
        self.assertEqual(ej.parse_year(empty, 2026, reference_date=date(2026, 1, 2)), [])
        with self.assertRaisesRegex(ValueError, "incomplete"):
            ej.parse_year(empty, 2026, reference_date=date(2026, 1, 3))

    def test_unsorted_source_numbers_are_canonicalized(self):
        html = one_row(numbers=(38, 10, 34, 29, 15), euros=(9, 2))
        draw = ej.parse_year(html, 2026, reference_date=date(2026, 1, 3))[0]
        self.assertEqual(draw[1:], (10, 15, 29, 34, 38, 2, 9))


class TestRules(unittest.TestCase):
    def test_historical_euro_number_pool_boundaries(self):
        for day, maximum in ((date(2014, 10, 3), 8), (date(2014, 10, 10), 10),
                             (date(2022, 3, 18), 10), (date(2022, 3, 25), 12)):
            with self.subTest(day=day):
                self.assertEqual(ej.euro_number_max(day), maximum)
                self.assertTrue(ej.validate_draw(ej.Draw(day.isoformat(), 1, 2, 3, 4, 5, 1, maximum))[0])
                self.assertFalse(ej.validate_draw(ej.Draw(day.isoformat(), 1, 2, 3, 4, 5, 1, maximum + 1))[0])

    def test_first_tuesday_and_start_date(self):
        for day, expected in ((date(2012, 3, 16), False), (date(2012, 3, 23), True),
                              (date(2022, 3, 22), False), (date(2022, 3, 29), True)):
            with self.subTest(day=day):
                self.assertEqual(ej.is_draw_date(day), expected)

    def test_expected_annual_schedule_counts(self):
        for year, count in ((2012, 41), (2013, 52), (2021, 53), (2022, 92), (2025, 104)):
            with self.subTest(year=year):
                self.assertEqual(len(ej.expected_draw_dates(year, through=date(year, 12, 31))), count)

    def test_invalid_numbers_and_dates(self):
        for draw in (FIRST._replace(n1=0), FIRST._replace(n2=5), FIRST._replace(e2=6),
                     FIRST._replace(n1=7, n2=5), FIRST._replace(e1=8, e2=6),
                     FIRST._replace(date="20120323"), FIRST._replace(date="2012-02-30")):
            with self.subTest(draw=draw):
                self.assertFalse(ej.validate_draw(draw)[0])

    def test_url_rule_and_rollover(self):
        self.assertEqual(ej.archive_url(2026, current_year=2026), ej.ARCHIVE_URL)
        self.assertEqual(ej.archive_url(2012, current_year=2026), ej.ARCHIVE_URL + "?j=2012")
        self.assertEqual(ej.archive_url(2026, current_year=2027), ej.ARCHIVE_URL + "?j=2026")
        self.assertEqual(ej.archive_url(2027, current_year=2027), ej.ARCHIVE_URL)
        for invalid in (2011, 2027):
            with self.assertRaises(ValueError):
                ej.archive_url(invalid, current_year=2026)


class TestFetchingAndStorage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "results.csv"
        self.patcher = patch.object(ej, "RESULTS_CSV", self.path)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_real_fixture_import_is_idempotent(self):
        html = FIXTURE.read_text(encoding="utf-8")
        with patch.object(ej, "fetch_url", return_value=html), contextlib.redirect_stdout(io.StringIO()):
            draws = ej.fetch_new_draws(start_year=2012, end_year=2012)
            ej.write_draws(draws)
            before = self.path.read_bytes()
            self.assertEqual(ej.fetch_new_draws(start_year=2012, end_year=2012), [])
            self.assertEqual(self.path.read_bytes(), before)

    def test_source_correction_is_detected(self):
        ej.write_draws([FIRST._replace(n1=4)])
        html = FIXTURE.read_text(encoding="utf-8")
        with patch.object(ej, "fetch_url", return_value=html), contextlib.redirect_stdout(io.StringIO()):
            draws = ej.fetch_new_draws(start_year=2012, end_year=2012)
        self.assertIn(FIRST, draws)

    def test_failed_later_year_leaves_existing_archive_untouched(self):
        ej.write_draws([FIRST])
        before = self.path.read_bytes()
        with patch.object(ej, "fetch_url", side_effect=[FIXTURE.read_text(), RuntimeError("source offline")]), \
                patch.object(ej.time, "sleep"), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            result = ej.main(["--start-year", "2012", "--end-year", "2013"])
        self.assertEqual(result, -1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_archive_bootstraps_all_years(self):
        with patch.object(ej, "fetch_url", return_value="stub") as get, \
                patch.object(ej, "parse_year", return_value=[]), patch.object(ej.time, "sleep"), \
                contextlib.redirect_stdout(io.StringIO()):
            ej.fetch_new_draws()
        self.assertEqual(get.call_args_list[0].args[0], ej.ARCHIVE_URL + "?j=2012")
        self.assertEqual(get.call_args_list[-1].args[0], ej.ARCHIVE_URL)
        self.assertEqual(get.call_count, date.today().year - 2012 + 1)

    def test_bad_year_range_makes_no_requests(self):
        with patch.object(ej, "fetch_url") as get:
            for bounds in ((2011, 2012), (2020, 2019), (2012, date.today().year + 1)):
                with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                    ej.fetch_new_draws(start_year=bounds[0], end_year=bounds[1])
            get.assert_not_called()

    def test_regular_update_repairs_an_interrupted_history_import(self):
        ej.write_draws([FIRST])
        with patch.object(ej, "fetch_url", return_value="stub") as get, \
                patch.object(ej, "parse_year", return_value=[]), patch.object(ej.time, "sleep"), \
                contextlib.redirect_stdout(io.StringIO()):
            ej.fetch_new_draws()
        self.assertEqual(get.call_args_list[0].args[0], ej.ARCHIVE_URL + "?j=2012")

    def test_unknown_cli_argument_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exc:
            ej.main(["--inti"])
        self.assertEqual(exc.exception.code, 2)

    def test_commit_recovers_previously_written_data_without_new_draws(self):
        ej.write_draws([FIRST])
        with patch.object(ej, "fetch_new_draws", return_value=[]), \
                patch.object(ej, "git_commit", return_value=True) as commit, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ej.main(["--commit"]), 0)
        commit.assert_called_once_with(str(self.path), "Update EU Eurojackpot results")

    def test_normal_update_does_not_require_git(self):
        with patch.object(ej, "fetch_new_draws", return_value=[FIRST]), \
                patch.object(ej, "git_commit") as commit, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ej.main([]), 1)
        commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
