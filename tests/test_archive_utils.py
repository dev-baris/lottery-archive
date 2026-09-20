"""Regression coverage for archive preservation and source validation."""

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import NamedTuple
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from archive_utils import read_draws, validate_iso_date, validate_source_draws, write_draws_atomic


class SampleDraw(NamedTuple):
    date: str
    number: int
    bonus: int | None


def validate(draw):
    valid, reason = validate_iso_date(draw.date)
    if not valid:
        return valid, reason
    return (True, "") if 1 <= draw.number <= 50 else (False, "number out of range")


class TestArchiveSafety(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "results.csv"
        self.nullable = frozenset({"bonus"})
        self.original = b"date,number,bonus\n2025-01-03,5,\n"
        self.path.write_bytes(self.original)

    def write(self, draws):
        write_draws_atomic(self.path, draws, SampleDraw, validate, nullable_fields=self.nullable)

    def read(self):
        return read_draws(self.path, SampleDraw, validate, nullable_fields=self.nullable)

    def test_merge_preserves_existing_and_sorts(self):
        self.write([SampleDraw("2025-01-10", 20, 2), SampleDraw("2025-01-07", 10, 1)])
        self.assertEqual(self.read(), [
            SampleDraw("2025-01-03", 5, None), SampleDraw("2025-01-07", 10, 1),
            SampleDraw("2025-01-10", 20, 2),
        ])

    def test_failed_replace_preserves_original_and_removes_temporary(self):
        with patch("archive_utils.os.replace", side_effect=OSError("disk failure")):
            with self.assertRaisesRegex(OSError, "disk failure"):
                self.write([SampleDraw("2025-01-07", 10, 1)])
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_corrupt_existing_rows_abort_without_losing_data(self):
        for corruption in (
            b"date,number,bonus\n2025-01-03,bad,\n",
            b"date,number,bonus\n2025-01-03,5\n",
            b"date,number,bonus\n2025-01-03,5,,unexpected\n",
            b"date,number,bonus\n2025-02-30,5,\n",
            b"date,number,bonus\n2025-01-03,5,\n2025-01-03,5,\n",
            b"date,wrong,bonus\n2025-01-03,5,\n",
            b"",
        ):
            with self.subTest(corruption=corruption):
                self.path.write_bytes(corruption)
                with self.assertRaises(ValueError):
                    self.write([SampleDraw("2025-01-07", 10, 1)])
                self.assertEqual(self.path.read_bytes(), corruption)

    def test_invalid_incoming_draw_preserves_original(self):
        with self.assertRaisesRegex(ValueError, "invalid draw"):
            self.write([SampleDraw("2025-01-07", 51, 1)])
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_conflicting_incoming_draws_preserve_original(self):
        with self.assertRaisesRegex(ValueError, "conflicting incoming"):
            self.write([SampleDraw("2025-01-07", 5, 1), SampleDraw("2025-01-07", 6, 1)])
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_explicit_replacement_keeps_one_row(self):
        self.write([SampleDraw("2025-01-03", 6, 1)])
        self.assertEqual(self.read(), [SampleDraw("2025-01-03", 6, 1)])

    def test_utf8_bom_header_is_supported(self):
        self.path.write_bytes(b"\xef\xbb\xbf" + self.original)
        self.assertEqual(self.read(), [SampleDraw("2025-01-03", 5, None)])

    def test_blank_required_numeric_field_is_rejected(self):
        with self.assertRaises(ValueError):
            read_draws(self.path, SampleDraw, validate)


class TestSourceValidation(unittest.TestCase):
    def test_canonical_calendar_dates_required(self):
        for invalid in ("2025-02-30", "2025-2-3", "20250203", "2025-W01-1", ""):
            with self.subTest(invalid=invalid):
                self.assertFalse(validate_iso_date(invalid)[0])
        self.assertTrue(validate_iso_date("2024-02-29")[0])

    def test_empty_scrape_is_a_failure(self):
        with self.assertRaisesRegex(ValueError, "no valid draws"):
            validate_source_draws([], "test source")
        self.assertEqual(validate_source_draws([], "unpublished year", allow_empty=True), [])

    def test_misrouted_year_is_a_failure(self):
        with self.assertRaisesRegex(ValueError, "requested 2026"):
            validate_source_draws([SampleDraw("2025-01-03", 5, 1)], "test source", year=2026)

    def test_future_draw_is_a_failure(self):
        with self.assertRaisesRegex(ValueError, "future draw"):
            validate_source_draws(
                [SampleDraw("2026-12-31", 5, 1)], "test source", today=date(2026, 9, 20),
            )

    def test_identical_duplicates_deduplicate_but_conflicts_raise(self):
        draw = SampleDraw("2025-01-03", 5, 1)
        self.assertEqual(validate_source_draws([draw, draw], "test source"), [draw])
        with self.assertRaisesRegex(ValueError, "conflicting draws"):
            validate_source_draws([draw, draw._replace(number=6)], "test source")


if __name__ == "__main__":
    unittest.main()
