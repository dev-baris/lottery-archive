"""
Unit tests for check_integrity.py

All tests work with temporary CSV files — no network requests are made.
"""

import csv
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from check_integrity import GAMES, GameRules, check_csv, main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_rules(path: Path, game: str) -> GameRules:
    game_id = "euromillions" if game == "eu" else game
    return replace(next(rules for rules in GAMES if rules.game_id == game_id),
                   csv_path=path)


def write_csv(path: Path, fieldnames: list, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def validate_rows(game: str, rows: list[dict], *,
                  reference_date: date = date(2026, 9, 20),
                  skip_stale: bool = True) -> tuple[list[str], int]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "results.csv"
        rules = make_rules(path, game)
        write_csv(path, rules.fieldnames, rows)
        return check_csv(rules, reference_date=reference_date, skip_stale=skip_stale)


AT_FIELDS = ["date", "n1", "n2", "n3", "n4", "n5", "n6", "zusatzzahl"]
DE_FIELDS = ["date", "n1", "n2", "n3", "n4", "n5", "n6", "superzahl"]
EU_FIELDS = ["date", "n1", "n2", "n3", "n4", "n5", "s1", "s2"]

VALID_AT_ROW = {"date": "2025-01-04", "n1": 1, "n2": 4, "n3": 15,
                "n4": 16, "n5": 22, "n6": 38, "zusatzzahl": 11}
VALID_AT_ROW2 = {"date": "2025-01-08", "n1": 3, "n2": 9, "n3": 18,
                 "n4": 27, "n5": 33, "n6": 41, "zusatzzahl": 5}
VALID_DE_ROW = {"date": "2021-01-02", "n1": 5, "n2": 11, "n3": 13,
                "n4": 20, "n5": 38, "n6": 40, "superzahl": 8}
VALID_EU_ROW = {"date": "2025-01-03", "n1": 3, "n2": 19, "n3": 29,
                "n4": 35, "n5": 37, "s1": 1, "s2": 9}
VALID_EU_ROW2 = {"date": "2025-01-07", "n1": 12, "n2": 17, "n3": 27,
                 "n4": 44, "n5": 50, "s1": 4, "s2": 11}
VALID_EUROJACKPOT_ROW = {"date": "2025-01-03", "n1": 3, "n2": 19, "n3": 29,
                        "n4": 35, "n5": 37, "e1": 1, "e2": 9}


# ---------------------------------------------------------------------------
# Valid data
# ---------------------------------------------------------------------------

class TestValidData(unittest.TestCase):
    def test_clean_at_csv_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "at.csv"
            write_csv(p, AT_FIELDS, [VALID_AT_ROW, VALID_AT_ROW2])
            errors, count = check_csv(make_rules(p, "at"),
                                      reference_date=date(2025, 1, 8))
            self.assertEqual(errors, [])
            self.assertEqual(count, 2)

    def test_clean_de_csv_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "de.csv"
            write_csv(p, DE_FIELDS, [VALID_DE_ROW])
            errors, count = check_csv(make_rules(p, "de"),
                                      reference_date=date(2021, 1, 2))
            self.assertEqual(errors, [])
            self.assertEqual(count, 1)

    def test_clean_eu_csv_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "eu.csv"
            write_csv(p, EU_FIELDS, [VALID_EU_ROW, VALID_EU_ROW2])
            errors, count = check_csv(make_rules(p, "eu"),
                                      reference_date=date(2025, 1, 7))
            self.assertEqual(errors, [])
            self.assertEqual(count, 2)


class TestArchiveRetention(unittest.TestCase):
    def test_lotto_records_before_2000_are_rejected(self):
        for game, row in [("at", VALID_AT_ROW), ("de", VALID_DE_ROW)]:
            with self.subTest(game=game):
                errors, count = validate_rows(game, [{**row, "date": "1999-12-31"}])
                self.assertEqual(count, 1)
                self.assertTrue(any("date precedes archive start on 2000-01-01" in error
                                    for error in errors))

    def test_lotto_retention_includes_all_of_2000(self):
        for game, row in [("at", VALID_AT_ROW), ("de", VALID_DE_ROW)]:
            for draw_date in ["2000-01-01", "2000-02-29", "2000-12-31"]:
                with self.subTest(game=game, date=draw_date):
                    errors, count = validate_rows(game, [{**row, "date": draw_date}])
                    # The retention boundary is independent of scheduled weekdays.
                    self.assertFalse(any("archive start" in error for error in errors))
                    if game == "at" or draw_date == "2000-01-01":
                        self.assertEqual(errors, [])
                    self.assertEqual(count, 1)

    def test_pre_2000_rows_are_reported_in_mixed_archives(self):
        for game, row in [("at", VALID_AT_ROW), ("de", VALID_DE_ROW)]:
            with self.subTest(game=game):
                rows = [{**row, "date": "1999-12-31"},
                        {**row, "date": "2000-01-01"}]
                errors, count = validate_rows(game, rows)
                self.assertEqual(count, 2)
                cutoff_errors = [error for error in errors if "archive start" in error]
                self.assertEqual(len(cutoff_errors), 1)
                self.assertIn("Row 2 (1999-12-31)", cutoff_errors[0])
                self.assertIn("archive start on 2000-01-01", cutoff_errors[0])

    def test_archive_retention_does_not_change_game_history(self):
        cases = [("at", date(1986, 9, 7)), ("de", date(1955, 10, 9))]
        for game, first_draw in cases:
            with self.subTest(game=game):
                rules = make_rules(Path("unused.csv"), game)
                self.assertEqual(rules.first_draw, first_draw)
                self.assertEqual(rules.archive_start, date(2000, 1, 1))

    def test_european_games_keep_their_launch_dates(self):
        cases = [("eu", VALID_EU_ROW, date(2004, 2, 13)),
                 ("eurojackpot", {**VALID_EUROJACKPOT_ROW, "e2": 8},
                  date(2012, 3, 23))]
        for game, row, first_draw in cases:
            with self.subTest(game=game):
                rules = make_rules(Path("unused.csv"), game)
                self.assertEqual(rules.first_draw, first_draw)
                self.assertIsNone(rules.archive_start)
                errors, count = validate_rows(
                    game, [{**row, "date": first_draw.isoformat()}]
                )
                self.assertEqual(errors, [])
                self.assertEqual(count, 1)
                errors, _ = validate_rows(
                    game, [{**row, "date": (first_draw - timedelta(days=7)).isoformat()}]
                )
                self.assertTrue(any("precedes first draw" in error for error in errors))
                self.assertFalse(any("archive start" in error for error in errors))


# ---------------------------------------------------------------------------
# Duplicate dates
# ---------------------------------------------------------------------------

class TestDuplicateDates(unittest.TestCase):
    def test_duplicate_date_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "at.csv"
            row2 = {**VALID_AT_ROW, "n1": 2}  # same date, different numbers
            write_csv(p, AT_FIELDS, [VALID_AT_ROW, row2])
            errors, _ = check_csv(make_rules(p, "at"))
            self.assertTrue(any("duplicate" in e for e in errors))


# ---------------------------------------------------------------------------
# Number ranges
# ---------------------------------------------------------------------------

class TestNumberRanges(unittest.TestCase):
    def test_at_number_46_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "at.csv"
            write_csv(p, AT_FIELDS, [{**VALID_AT_ROW, "n6": 46}])
            errors, _ = check_csv(make_rules(p, "at"))
            self.assertTrue(any("out of range" in e for e in errors))

    def test_de_number_50_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "de.csv"
            write_csv(p, DE_FIELDS, [{**VALID_DE_ROW, "n6": 50}])
            errors, _ = check_csv(make_rules(p, "de"))
            self.assertTrue(any("out of range" in e for e in errors))

    def test_de_superzahl_10_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "de.csv"
            write_csv(p, DE_FIELDS, [{**VALID_DE_ROW, "superzahl": 10}])
            errors, _ = check_csv(make_rules(p, "de"))
            self.assertTrue(any("superzahl" in e for e in errors))

    def test_de_historical_empty_superzahl_is_outside_archive_scope(self):
        """A historically valid pre-Superzahl draw is still outside retention."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "de.csv"
            write_csv(p, DE_FIELDS, [{**VALID_DE_ROW, "date": "1991-11-30",
                                      "superzahl": ""}])
            errors, _ = check_csv(make_rules(p, "de"),
                                  reference_date=date(1991, 11, 30))
            self.assertTrue(any("date precedes archive start on 2000-01-01" in error
                                for error in errors))

    def test_at_zusatzzahl_0_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "at.csv"
            write_csv(p, AT_FIELDS, [{**VALID_AT_ROW, "zusatzzahl": 0}])
            errors, _ = check_csv(make_rules(p, "at"))
            self.assertTrue(any("zusatzzahl" in e for e in errors))

    def test_eu_main_number_51_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "eu.csv"
            write_csv(p, EU_FIELDS, [{**VALID_EU_ROW, "n5": 51}])
            errors, _ = check_csv(make_rules(p, "eu"))
            self.assertTrue(any("out of range" in e for e in errors))

    def test_eu_star_13_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "eu.csv"
            write_csv(p, EU_FIELDS, [{**VALID_EU_ROW, "s2": 13}])
            errors, _ = check_csv(make_rules(p, "eu"))
            self.assertTrue(any("s2" in e for e in errors))

    def test_eu_duplicate_stars_reported(self):
        """Two identical star numbers in one row must be flagged."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "eu.csv"
            write_csv(p, EU_FIELDS, [{**VALID_EU_ROW, "s1": 9, "s2": 9}])
            errors, _ = check_csv(make_rules(p, "eu"))
            self.assertTrue(any("duplicate" in e for e in errors))


# ---------------------------------------------------------------------------
# Sort order
# ---------------------------------------------------------------------------

class TestSortOrder(unittest.TestCase):
    def test_unsorted_dates_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "at.csv"
            # Write in reverse order (newer date first)
            write_csv(p, AT_FIELDS, [VALID_AT_ROW2, VALID_AT_ROW])
            errors, _ = check_csv(make_rules(p, "at"))
            self.assertTrue(any("sorted" in e for e in errors))


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_missing_file_reported(self):
        errors, count = check_csv(make_rules(Path("/nonexistent/path.csv"), "at"))
        self.assertTrue(any("not found" in e for e in errors))
        self.assertEqual(count, 0)

    def test_empty_file_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "at.csv"
            write_csv(p, AT_FIELDS, [])
            errors, count = check_csv(make_rules(p, "at"))
            self.assertTrue(any("empty" in e for e in errors))
            self.assertEqual(count, 0)


# ---------------------------------------------------------------------------
# Stale data detection
# ---------------------------------------------------------------------------

class TestStaleData(unittest.TestCase):
    def test_fresh_data_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "at.csv"
            today = date.today()
            row = {**VALID_AT_ROW, "date": today.isoformat()}
            write_csv(p, AT_FIELDS, [row])
            rules = make_rules(p, "at")
            errors, _ = check_csv(rules, reference_date=today)
            self.assertFalse(any("stale" in e for e in errors))

    def test_data_within_threshold_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "at.csv"
            last_draw = date(2025, 1, 1)
            row = {**VALID_AT_ROW, "date": last_draw.isoformat()}
            write_csv(p, AT_FIELDS, [row])
            rules = make_rules(p, "at")
            # 6 days since last draw, threshold is 7 → OK
            reference = last_draw + timedelta(days=6)
            errors, _ = check_csv(rules, reference_date=reference)
            self.assertFalse(any("stale" in e for e in errors))

    def test_stale_data_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "at.csv"
            last_draw = date(2025, 1, 1)
            row = {**VALID_AT_ROW, "date": last_draw.isoformat()}
            write_csv(p, AT_FIELDS, [row])
            rules = make_rules(p, "at")
            # 10 days since last draw, threshold is 7 → stale
            reference = last_draw + timedelta(days=10)
            errors, _ = check_csv(rules, reference_date=reference)
            self.assertTrue(any("stale" in e for e in errors))

    def test_stale_error_mentions_last_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "at.csv"
            last_draw = date(2025, 3, 15)
            row = {**VALID_AT_ROW, "date": last_draw.isoformat()}
            write_csv(p, AT_FIELDS, [row])
            rules = make_rules(p, "at")
            reference = last_draw + timedelta(days=14)
            errors, _ = check_csv(rules, reference_date=reference)
            self.assertTrue(any("2025-03-15" in e for e in errors))

    def test_skip_stale_suppresses_stale_error(self):
        """With skip_stale=True, stale data must not be reported."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "at.csv"
            last_draw = date(2025, 1, 1)
            row = {**VALID_AT_ROW, "date": last_draw.isoformat()}
            write_csv(p, AT_FIELDS, [row])
            rules = make_rules(p, "at")
            reference = last_draw + timedelta(days=30)
            errors, _ = check_csv(rules, reference_date=reference, skip_stale=True)
            self.assertFalse(any("stale" in e for e in errors))

    def test_skip_stale_still_catches_other_errors(self):
        """skip_stale=True must not suppress unrelated errors like duplicates."""
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "at.csv"
            row2 = {**VALID_AT_ROW, "n1": 2}
            write_csv(p, AT_FIELDS, [VALID_AT_ROW, row2])  # duplicate date
            rules = make_rules(p, "at")
            errors, _ = check_csv(rules, skip_stale=True)
            self.assertTrue(any("duplicate" in e for e in errors))

    def test_future_draw_cannot_mask_stale_archive(self):
        rows = [{**VALID_AT_ROW, "date": "2025-01-01"},
                {**VALID_AT_ROW2, "date": "2025-02-01"}]
        errors, count = validate_rows("at", rows, reference_date=date(2025, 1, 15),
                                      skip_stale=False)
        self.assertEqual(count, 2)
        self.assertTrue(any("future" in error for error in errors))
        self.assertTrue(any("stale" in error and "2025-01-01" in error
                            for error in errors))

    def test_skip_stale_still_rejects_future_date(self):
        errors, _ = validate_rows("at", [VALID_AT_ROW],
                                  reference_date=date(2025, 1, 1))
        self.assertTrue(any("future" in error for error in errors))


class TestCsvSchemaAndDates(unittest.TestCase):
    def test_wrong_missing_or_duplicate_header_is_reported(self):
        headers = [AT_FIELDS[:-1] + ["bonus"], AT_FIELDS[:-1],
                   AT_FIELDS[:-1] + ["n6"], list(reversed(AT_FIELDS))]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.csv"
            for header in headers:
                with self.subTest(header=header):
                    with path.open("w", newline="", encoding="utf-8") as handle:
                        writer = csv.writer(handle)
                        writer.writerow(header)
                        writer.writerow(VALID_AT_ROW.values())
                    errors, count = check_csv(make_rules(path, "at"), skip_stale=True)
                    self.assertEqual(count, 1)
                    self.assertTrue(any("header" in error for error in errors))

    def test_short_and_extra_column_records_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.csv"
            values = list(VALID_AT_ROW.values())
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(AT_FIELDS)
                writer.writerow(values[:-1])
                writer.writerow(values + ["unexpected"])
                writer.writerow(values)
            errors, count = check_csv(make_rules(path, "at"), skip_stale=True)
            self.assertEqual(count, 3)
            self.assertEqual(len(errors), 2)
            self.assertTrue(any("Row 2" in error and "columns" in error
                                for error in errors))
            self.assertTrue(any("Row 3" in error and "columns" in error
                                for error in errors))

    def test_noncanonical_or_invalid_dates_are_rejected(self):
        for raw_date in ["20250104", "2025-W01-6", "2025-1-4", "2025-02-30",
                         "04.01.2025", "", " 2025-01-04"]:
            with self.subTest(date=raw_date):
                errors, _ = validate_rows("at", [{**VALID_AT_ROW, "date": raw_date}])
                self.assertTrue(any("invalid date" in error for error in errors))

    def test_diagnostics_keep_physical_line_numbers_after_bad_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(AT_FIELDS)
                writer.writerow(["malformed"])
                writer.writerow(VALID_AT_ROW.values())
                writer.writerow(VALID_AT_ROW.values())
            errors, count = check_csv(make_rules(path, "at"), skip_stale=True)
            self.assertEqual(count, 3)
            self.assertTrue(any("Row 2" in error and "columns" in error
                                for error in errors))
            self.assertTrue(any("Row 4" in error and "duplicate date" in error
                                and "row 3" in error for error in errors))

    def test_invalid_main_number_is_reported_without_crashing(self):
        errors, _ = validate_rows("at", [{**VALID_AT_ROW, "n2": "invalid"}])
        self.assertTrue(any("could not parse numbers" in error for error in errors))

    def test_duplicate_main_number_is_reported(self):
        errors, _ = validate_rows("at", [{**VALID_AT_ROW, "n2": VALID_AT_ROW["n1"]}])
        self.assertTrue(any("duplicate numbers" in error for error in errors))


class TestExtraNumbers(unittest.TestCase):
    def test_current_draws_require_every_extra_field(self):
        cases = [("at", VALID_AT_ROW, "zusatzzahl"),
                 ("de", VALID_DE_ROW, "superzahl"),
                 ("eu", VALID_EU_ROW, "s1"), ("eu", VALID_EU_ROW, "s2"),
                 ("eurojackpot", VALID_EUROJACKPOT_ROW, "e1"),
                 ("eurojackpot", VALID_EUROJACKPOT_ROW, "e2")]
        for game, row, field in cases:
            with self.subTest(game=game, field=field):
                errors, _ = validate_rows(game, [{**row, field: " "}])
                self.assertTrue(any(f"missing required {field}" in error
                                    for error in errors))

    def test_superzahl_is_required_throughout_retained_archive(self):
        cases = [("2000-01-01", "", False), ("2000-01-01", 0, True),
                 ("2000-01-01", 9, True), ("2000-01-01", 10, False),
                 ("2026-09-19", "", False), ("2026-09-19", 0, True)]
        for draw_date, superzahl, accepted in cases:
            with self.subTest(date=draw_date, superzahl=superzahl):
                errors, _ = validate_rows("de", [{**VALID_DE_ROW, "date": draw_date,
                                                  "superzahl": superzahl}])
                self.assertEqual(errors == [], accepted)
                if superzahl == "":
                    self.assertTrue(any("missing required superzahl" in error
                                        for error in errors))

    def test_at_bonus_cannot_repeat_main_number(self):
        errors, _ = validate_rows("at", [{**VALID_AT_ROW, "zusatzzahl": 15}])
        self.assertTrue(any("duplicates a main number" in error for error in errors))

    def test_separate_pool_extras_can_repeat_main_numbers(self):
        for game, row, field in [("de", VALID_DE_ROW, "superzahl"),
                                 ("eu", VALID_EU_ROW, "s1"),
                                 ("eurojackpot", VALID_EUROJACKPOT_ROW, "e1")]:
            with self.subTest(game=game):
                errors, _ = validate_rows(game, [{**row, field: row["n1"]}])
                self.assertEqual(errors, [])

    def test_unsorted_main_numbers_are_rejected(self):
        row = {**VALID_AT_ROW, "n1": VALID_AT_ROW["n2"], "n2": VALID_AT_ROW["n1"]}
        errors, _ = validate_rows("at", [row])
        self.assertTrue(any("main numbers are not sorted" in error for error in errors))

    def test_unsorted_extra_numbers_are_rejected(self):
        for game, row, fields in [("eu", VALID_EU_ROW, ("s1", "s2")),
                                   ("eurojackpot", VALID_EUROJACKPOT_ROW, ("e1", "e2"))]:
            with self.subTest(game=game):
                first, second = fields
                errors, _ = validate_rows(game, [{**row, first: row[second],
                                                   second: row[first]}])
                self.assertTrue(any("extra numbers are not sorted" in error
                                    for error in errors))

    def test_invalid_extra_number_is_reported_without_crashing(self):
        errors, _ = validate_rows("de", [{**VALID_DE_ROW, "superzahl": "invalid"}])
        self.assertTrue(any("could not parse superzahl" in error for error in errors))

    def test_euromillions_historical_star_pool_boundaries(self):
        cases = [("2004-02-13", 9), ("2011-05-06", 9), ("2011-05-10", 11),
                 ("2016-09-23", 11), ("2016-09-27", 12)]
        for draw_date, maximum in cases:
            with self.subTest(date=draw_date):
                row = {**VALID_EU_ROW, "date": draw_date, "s2": maximum}
                errors, _ = validate_rows("eu", [row])
                self.assertEqual(errors, [])
                errors, _ = validate_rows("eu", [{**row, "s2": maximum + 1}])
                self.assertTrue(any("s2" in error and "out of range" in error
                                    for error in errors))

    def test_euromillions_draw_calendar_change(self):
        for draw_date, accepted in [("2011-05-03", False), ("2011-05-06", True),
                                    ("2011-05-10", True), ("2011-05-11", False)]:
            with self.subTest(date=draw_date):
                errors, _ = validate_rows("eu", [{**VALID_EU_ROW, "date": draw_date}])
                self.assertEqual(errors == [], accepted)

    def test_euromillions_missing_internal_draw_is_reported(self):
        rows = [{**VALID_EU_ROW, "date": draw_date}
                for draw_date in ["2011-05-06", "2011-05-13"]]
        errors, _ = validate_rows("eu", rows)
        self.assertTrue(any("Missing scheduled draw" in error and "2011-05-10" in error
                            for error in errors))


class TestGermanDrawCalendar(unittest.TestCase):
    @staticmethod
    def rows_for_2000() -> list[dict]:
        """53 Saturdays plus four December Wednesdays in the unified archive."""
        dates = [date(2000, 1, 1) + timedelta(weeks=week) for week in range(53)]
        dates += [date(2000, 12, day) for day in (6, 13, 20, 27)]
        return [{**VALID_DE_ROW, "date": draw_date.isoformat()}
                for draw_date in sorted(dates)]

    def test_complete_2000_archive_has_57_draws_without_false_wednesday_gaps(self):
        errors, count = validate_rows("de", self.rows_for_2000())
        self.assertEqual(errors, [])
        self.assertEqual(count, 57)

    def test_missing_2000_saturday_or_december_wednesday_is_reported(self):
        for omitted in ["2000-01-08", "2000-12-13"]:
            with self.subTest(omitted=omitted):
                rows = [row for row in self.rows_for_2000() if row["date"] != omitted]
                errors, count = validate_rows("de", rows)
                self.assertEqual(count, 56)
                self.assertEqual(len(errors), 1)
                self.assertIn(f"Missing scheduled draw(s) within archive: {omitted}",
                              errors[0])

    def test_wednesdays_before_unification_are_outside_this_draw_calendar(self):
        for draw_date in ["2000-01-05", "2000-11-29"]:
            with self.subTest(date=draw_date):
                errors, _ = validate_rows("de", [{**VALID_DE_ROW, "date": draw_date}])
                self.assertEqual(len(errors), 1)
                self.assertIn("not a scheduled draw day", errors[0])
                self.assertNotIn("archive start", errors[0])

    def test_first_unified_wednesday_and_surrounding_saturdays_pass(self):
        rows = [{**VALID_DE_ROW, "date": draw_date}
                for draw_date in ["2000-12-02", "2000-12-06", "2000-12-09"]]
        errors, count = validate_rows("de", rows)
        self.assertEqual(errors, [])
        self.assertEqual(count, 3)

    def test_wednesday_gaps_after_2000_are_reported(self):
        rows = [{**VALID_DE_ROW, "date": draw_date}
                for draw_date in ["2001-01-06", "2001-01-13"]]
        errors, _ = validate_rows("de", rows)
        self.assertTrue(any("Missing scheduled draw" in error and "2001-01-10" in error
                            for error in errors))

    def test_modern_draw_on_another_weekday_is_rejected(self):
        errors, _ = validate_rows("de", [{**VALID_DE_ROW, "date": "2026-09-18"}])
        self.assertTrue(any("not a scheduled draw day" in error for error in errors))


class TestEurojackpot(unittest.TestCase):
    def test_historical_euro_number_pool_boundaries(self):
        cases = [("2012-03-23", 8), ("2014-10-03", 8), ("2014-10-10", 10),
                 ("2022-03-18", 10), ("2022-03-25", 12)]
        for draw_date, maximum in cases:
            with self.subTest(date=draw_date):
                row = {**VALID_EUROJACKPOT_ROW, "date": draw_date, "e2": maximum}
                errors, count = validate_rows("eurojackpot", [row])
                self.assertEqual(errors, [])
                self.assertEqual(count, 1)
                errors, _ = validate_rows("eurojackpot", [{**row, "e2": maximum + 1}])
                self.assertTrue(any("e2" in error and "out of range" in error
                                    for error in errors))

    def test_duplicate_euro_numbers_are_rejected(self):
        errors, _ = validate_rows("eurojackpot", [{**VALID_EUROJACKPOT_ROW, "e2": 1}])
        self.assertTrue(any("duplicate extra numbers" in error for error in errors))

    def test_draw_before_launch_is_rejected(self):
        row = {**VALID_EUROJACKPOT_ROW, "date": "2012-03-16", "e2": 8}
        errors, _ = validate_rows("eurojackpot", [row])
        self.assertTrue(any("precedes first draw" in error for error in errors))

    def test_tuesday_draw_introduction_and_invalid_weekday(self):
        for draw_date, accepted in [("2022-03-22", False), ("2022-03-25", True),
                                    ("2022-03-29", True), ("2022-03-30", False)]:
            with self.subTest(date=draw_date):
                row = {**VALID_EUROJACKPOT_ROW, "date": draw_date}
                errors, _ = validate_rows("eurojackpot", [row])
                if accepted:
                    self.assertEqual(errors, [])
                else:
                    self.assertTrue(any("not a scheduled draw day" in error
                                        for error in errors))

    def test_missing_internal_draw_is_reported(self):
        rows = [{**VALID_EUROJACKPOT_ROW, "date": draw_date}
                for draw_date in ["2025-01-03", "2025-01-10"]]
        errors, _ = validate_rows("eurojackpot", rows)
        self.assertTrue(any("Missing scheduled draw" in error and "2025-01-07" in error
                            for error in errors))

    def test_complete_draws_across_schedule_change_pass(self):
        rows = [{**VALID_EUROJACKPOT_ROW, "date": draw_date}
                for draw_date in ["2022-03-18", "2022-03-25", "2022-03-29", "2022-04-01"]]
        errors, count = validate_rows("eurojackpot", rows)
        self.assertEqual(errors, [])
        self.assertEqual(count, 4)


class TestCommandLineSelection(unittest.TestCase):
    def test_pre_2000_lotto_archive_fails_even_with_skip_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results.csv"
            for game, row in [("at", VALID_AT_ROW), ("de", VALID_DE_ROW)]:
                with self.subTest(game=game):
                    rules = make_rules(path, game)
                    write_csv(path, rules.fieldnames, [{**row, "date": "1999-12-31"}])
                    output = io.StringIO()
                    with patch("check_integrity.GAMES", [rules]), redirect_stdout(output):
                        status = main(["--game", game, "--skip-stale"])
                    self.assertEqual(status, 1)
                    self.assertIn("archive start on 2000-01-01", output.getvalue())

    def test_selectors_check_only_requested_game(self):
        for selector, game_id in [("--game eurojackpot", "eurojackpot"),
                                  ("--country eu", "euromillions")]:
            with self.subTest(selector=selector):
                output = io.StringIO()
                with patch("check_integrity.check_csv", return_value=([], 1)) as checker:
                    with redirect_stdout(output):
                        status = main([*selector.split(), "--skip-stale"])
                self.assertEqual(status, 0)
                checker.assert_called_once()
                self.assertEqual(checker.call_args.args[0].game_id, game_id)
                self.assertTrue(checker.call_args.kwargs["skip_stale"])

    def test_no_selector_checks_all_four_games(self):
        with patch("check_integrity.check_csv", return_value=([], 1)) as checker:
            with redirect_stdout(io.StringIO()):
                status = main([])
        self.assertEqual(status, 0)
        self.assertEqual({call.args[0].game_id for call in checker.call_args_list},
                         {"at", "de", "euromillions", "eurojackpot"})

    def test_validation_failure_sets_nonzero_exit_status(self):
        with patch("check_integrity.check_csv", return_value=(["invalid archive"], 1)):
            with redirect_stdout(io.StringIO()):
                status = main(["--game", "eurojackpot"])
        self.assertEqual(status, 1)


if __name__ == "__main__":
    unittest.main()
