"""
Unit tests for generate_page.py

All tests are offline — no network requests, no filesystem side-effects
except where a temporary directory is explicitly used.
"""

import csv
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import generate_page as gp


# ---------------------------------------------------------------------------
# read_last_row
# ---------------------------------------------------------------------------

class TestReadLastRow(unittest.TestCase):

    def _csv(self, rows):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
        ) as tmp:
            fieldnames = list(rows[0].keys())
            writer = csv.DictWriter(tmp, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        path = Path(tmp.name)
        self.addCleanup(path.unlink)
        return path

    def test_returns_last_row(self):
        path = self._csv([
            {"date": "2024-01-01", "n1": "1"},
            {"date": "2024-06-15", "n1": "7"},
            {"date": "2025-03-22", "n1": "42"},
        ])
        row = gp.read_last_row(path)
        self.assertEqual(row["date"], "2025-03-22")
        self.assertEqual(row["n1"], "42")

    def test_single_data_row(self):
        path = self._csv([{"date": "2020-05-10", "n1": "3"}])
        row = gp.read_last_row(path)
        self.assertEqual(row["date"], "2020-05-10")

    def test_returns_latest_date_from_unsorted_input(self):
        path = self._csv([
            {"date": "2025-06-06", "n1": "19"},
            {"date": "2025-01-03", "n1": "2"},
        ])
        self.assertEqual(gp.read_last_row(path)["n1"], "19")

    def test_invalid_date_reports_source_row(self):
        path = self._csv([{"date": "2025-02-30", "n1": "3"}])
        with self.assertRaisesRegex(ValueError, "invalid date at row 2"):
            gp.read_last_row(path)

    def test_missing_date_column_rejected(self):
        path = self._csv([{"n1": "3"}])
        with self.assertRaisesRegex(ValueError, "missing date column"):
            gp.read_last_row(path)

    def test_short_row_rejected(self):
        path = self._csv([{"date": "2025-01-03", "n1": "3"}])
        path.write_text("date,n1\n2025-01-03\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "malformed CSV row 2"):
            gp.read_last_row(path)

    def test_extra_column_rejected(self):
        path = self._csv([{"date": "2025-01-03", "n1": "3"}])
        path.write_text("date,n1\n2025-01-03,3,4\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "malformed CSV row 2"):
            gp.read_last_row(path)

    def test_duplicate_header_rejected(self):
        path = self._csv([{"date": "2025-01-03", "n1": "3"}])
        path.write_text("date,n1,n1\n2025-01-03,3,4\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate CSV columns"):
            gp.read_last_row(path)

    def test_returns_none_for_empty_csv(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write("date,n1\n")  # header only
        path = Path(f.name)
        self.addCleanup(path.unlink)
        self.assertIsNone(gp.read_last_row(path))


# ---------------------------------------------------------------------------
# format_date
# ---------------------------------------------------------------------------

class TestFormatDate(unittest.TestCase):

    def test_standard_date(self):
        self.assertEqual(gp.format_date("2025-04-12"), "12.04.2025")

    def test_single_digit_day_and_month(self):
        self.assertEqual(gp.format_date("2004-02-05"), "05.02.2004")

    def test_year_boundary(self):
        self.assertEqual(gp.format_date("2000-01-01"), "01.01.2000")


# ---------------------------------------------------------------------------
# render_lottery_card
# ---------------------------------------------------------------------------

class TestRenderLotteryCard(unittest.TestCase):

    AT = {
        "id": "at",
        "name": "Lotto 6 aus 45",
        "flag": "🇦🇹",
        "numbers": ["n1", "n2", "n3", "n4", "n5", "n6"],
        "bonus": [("Zusatzzahl", "zusatzzahl")],
        "bonus_style": "bonus-red",
    }

    EU = {
        "id": "eu",
        "name": "Euromillionen",
        "flag": "🇪🇺",
        "numbers": ["n1", "n2", "n3", "n4", "n5"],
        "bonus": [("Lucky Star", "s1"), ("Lucky Star", "s2")],
        "bonus_style": "bonus-eu",
    }

    def test_contains_draw_date(self):
        row = {"date": "2025-03-15", "n1": "5", "n2": "10", "n3": "15",
               "n4": "20", "n5": "25", "n6": "30", "zusatzzahl": "7"}
        html = gp.render_lottery_card(self.AT, row)
        self.assertIn("15.03.2025", html)

    def test_contains_all_main_numbers(self):
        row = {"date": "2025-01-01", "n1": "3", "n2": "17", "n3": "22",
               "n4": "31", "n5": "40", "n6": "45", "zusatzzahl": "12"}
        html = gp.render_lottery_card(self.AT, row)
        for num in ["3", "17", "22", "31", "40", "45"]:
            self.assertIn(num, html)

    def test_contains_bonus_number(self):
        row = {"date": "2025-01-01", "n1": "1", "n2": "2", "n3": "3",
               "n4": "4", "n5": "5", "n6": "6", "zusatzzahl": "9"}
        html = gp.render_lottery_card(self.AT, row)
        self.assertIn("bonus-red", html)
        self.assertIn(">9<", html)

    def test_empty_bonus_omitted(self):
        row = {"date": "2025-01-01", "n1": "1", "n2": "2", "n3": "3",
               "n4": "4", "n5": "5", "n6": "6", "zusatzzahl": ""}
        html = gp.render_lottery_card(self.AT, row)
        self.assertNotIn("bonus-red", html)
        self.assertNotIn("separator", html)

    def test_two_lucky_stars_rendered(self):
        row = {"date": "2025-02-01", "n1": "10", "n2": "20", "n3": "30",
               "n4": "40", "n5": "50", "s1": "3", "s2": "11"}
        html = gp.render_lottery_card(self.EU, row)
        self.assertEqual(html.count("bonus-eu"), 2)

    def test_lottery_name_in_card(self):
        row = {"date": "2025-01-01", "n1": "1", "n2": "2", "n3": "3",
               "n4": "4", "n5": "5", "n6": "6", "zusatzzahl": "7"}
        html = gp.render_lottery_card(self.AT, row)
        self.assertIn("Lotto 6 aus 45", html)

    def test_card_id_attribute(self):
        row = {"date": "2025-01-01", "n1": "1", "n2": "2", "n3": "3",
               "n4": "4", "n5": "5", "n6": "6", "zusatzzahl": "7"}
        html = gp.render_lottery_card(self.AT, row)
        self.assertIn('id="at"', html)

    def test_eurojackpot_uses_distinct_card_and_two_euro_numbers(self):
        lottery = next(item for item in gp.LOTTERIES if item["id"] == "eurojackpot")
        row = {"date": "2026-09-18", "n1": "4", "n2": "25", "n3": "30",
               "n4": "32", "n5": "33", "e1": "4", "e2": "5"}
        html = gp.render_lottery_card(lottery, row)
        self.assertIn('id="eurojackpot"', html)
        self.assertEqual(html.count('class="ball main"'), 5)
        self.assertEqual(html.count('title="Eurozahl"'), 2)
        self.assertIn('href="eu/eurojackpot/results.csv"', html)

    def test_csv_html_is_escaped(self):
        row = {"date": "2025-01-01", "n1": '<img src=x onerror="alert(1)">',
               "n2": "2", "n3": "3", "n4": "4", "n5": "5", "n6": "6",
               "zusatzzahl": "<script>alert(1)</script>"}
        lottery = {**self.AT, "name": 'Lotto & <script>bad</script>'}
        html = gp.render_lottery_card(lottery, row)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)
        self.assertIn("Lotto &amp; &lt;script&gt;", html)

    def test_zero_superzahl_rendered(self):
        lottery = next(item for item in gp.LOTTERIES if item["id"] == "de")
        row = {"date": "2025-01-01", "n1": 1, "n2": 2, "n3": 3,
               "n4": 4, "n5": 5, "n6": 6, "superzahl": 0}
        self.assertIn('aria-label="Superzahl 0">0</span>',
                      gp.render_lottery_card(lottery, row))


# ---------------------------------------------------------------------------
# generate_html
# ---------------------------------------------------------------------------

class TestGenerateHtml(unittest.TestCase):

    def test_contains_page_title(self):
        html = gp.generate_html([], "01.01.2025 12:00 UTC")
        self.assertIn("Lottery Archive", html)

    def test_contains_generated_timestamp(self):
        html = gp.generate_html([], "15.04.2026 08:30 UTC")
        self.assertIn("15.04.2026 08:30 UTC", html)

    def test_cards_included(self):
        html = gp.generate_html(["<article>Card A</article>", "<article>Card B</article>"], "x")
        self.assertIn("Card A", html)
        self.assertIn("Card B", html)

    def test_timestamp_is_escaped(self):
        html = gp.generate_html([], '<script>alert("bad")</script>')
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_valid_html_structure(self):
        html = gp.generate_html([], "x")
        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("<html", html)
        self.assertIn("</html>", html)
        self.assertIn("<body>", html)
        self.assertIn("</body>", html)


# ---------------------------------------------------------------------------
# main (integration)
# ---------------------------------------------------------------------------

class TestMain(unittest.TestCase):
    """Exercise the actual build function with isolated, deterministic inputs."""

    def _lotteries(self, root):
        lotteries = []
        for lottery in gp.LOTTERIES:
            path = root / "input" / lottery["archive_url"]
            path.parent.mkdir(parents=True)
            fields = ["date", *lottery["numbers"],
                      *(column for _, column in lottery["bonus"])]
            row = {"date": "2026-09-18"}
            row.update({column: i for i, column in enumerate(lottery["numbers"], start=1)})
            row.update({column: i for i, (_, column) in enumerate(lottery["bonus"], start=7)})
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow(row)
            lotteries.append({**lottery, "csv": path})
        return lotteries

    def test_builds_all_cards_and_linked_downloads(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            lotteries = self._lotteries(root)
            output_dir = root / "output" / "public"
            with patch.object(gp, "LOTTERIES", lotteries):
                index = gp.main(output_dir)
            self.assertEqual(index, output_dir / "index.html")
            html = index.read_text(encoding="utf-8")
            self.assertEqual(html.count('<article class="card"'), 4)
            self.assertIn("Eurojackpot", html)
            self.assertIn("Euromillionen", html)
            self.assertIn('id="eurojackpot"', html)
            for lottery in lotteries:
                self.assertIn(f'href="{lottery["archive_url"]}"', html)
                self.assertEqual(
                    (output_dir / lottery["archive_url"]).read_bytes(),
                    lottery["csv"].read_bytes(),
                )

    def test_empty_archive_does_not_replace_existing_page(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            lotteries = self._lotteries(root)
            lotteries[-1]["csv"].write_text("date,n1,n2,n3,n4,n5,e1,e2\n", encoding="utf-8")
            output_dir = root / "public"
            output_dir.mkdir()
            index = output_dir / "index.html"
            index.write_text("previous complete page", encoding="utf-8")
            with patch.object(gp, "LOTTERIES", lotteries):
                with self.assertRaisesRegex(ValueError, "No data found"):
                    gp.main(output_dir)
            self.assertEqual(index.read_text(encoding="utf-8"), "previous complete page")
            self.assertFalse((output_dir / "at").exists())

    def test_missing_archive_fails_before_writing_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            lotteries = self._lotteries(root)
            lotteries[-1]["csv"].unlink()
            output_dir = root / "public"
            with patch.object(gp, "LOTTERIES", lotteries):
                with self.assertRaises(FileNotFoundError):
                    gp.main(output_dir)
            self.assertFalse(output_dir.exists())

    def test_pre_2000_lotto_row_cannot_be_published_behind_a_current_result(self):
        for game in ("at", "de"):
            with self.subTest(game=game), tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                lotteries = self._lotteries(root)
                lottery = next(item for item in lotteries if item["id"] == game)
                content = lottery["csv"].read_text(encoding="utf-8")
                header, current = content.splitlines()
                old = "1999-12-31," + current.split(",", 1)[1]
                lottery["csv"].write_text(f"{header}\n{old}\n{current}\n", encoding="utf-8")
                output_dir = root / "public"
                output_dir.mkdir()
                index = output_dir / "index.html"
                index.write_text("previous valid page", encoding="utf-8")
                with patch.object(gp, "LOTTERIES", lotteries):
                    with self.assertRaisesRegex(ValueError, "precedes archive start.*2000-01-01"):
                        gp.main(output_dir)
                self.assertEqual(index.read_text(), "previous valid page")
                self.assertFalse((output_dir / lottery["archive_url"]).exists())


if __name__ == "__main__":
    unittest.main()
