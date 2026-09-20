#!/usr/bin/env python3
"""
Fetch EuroMillions results from win2day.at.

Two data sources:
  - Yearly CSVs (2017–present):
    https://statics.win2day.at/media/NN_W2D_STAT_EUML_{YEAR}.csv
  - Historical CSV (2004–2016):
    https://statics.win2day.at/media-nopagespeed/euromillionen-ergebnisse-2004-2017.csv

EuroMillions rules:
  - 5 main numbers drawn from 1–50
  - 2 star numbers: 1–9 initially, 1–11 from 2011-05-10,
    and 1–12 from 2016-09-27
  - Friday draws; Tuesday draws added on 2011-05-10

Usage:
  python fetch_euromillions.py            # fetch current + previous year
  python fetch_euromillions.py --init     # full historical import (2004 to present)
  python fetch_euromillions.py --commit   # fetch and git-commit if new data found
"""

import argparse
import csv
import io
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import NamedTuple

from archive_utils import (
    read_draws, report_parse_issue, validate_iso_date, validate_source_draws,
    write_draws_atomic,
)
from git_utils import git_commit
from http_utils import fetch_url, HTTPError

RESULTS_CSV = Path(__file__).parent.parent / "eu" / "euromillions" / "results.csv"

YEARLY_URL = "https://statics.win2day.at/media/NN_W2D_STAT_EUML_{year}.csv"
HISTORICAL_URL = (
    "https://statics.win2day.at/media-nopagespeed"
    "/euromillionen-ergebnisse-2004-2017.csv"
)

FIRST_YEARLY_YEAR = 2017
FIRST_YEAR = 2004

NUMBER_MIN, NUMBER_MAX = 1, 50
STAR_MIN, STAR_MAX = 1, 12

class Draw(NamedTuple):
    date: str   # ISO format: YYYY-MM-DD
    n1: int
    n2: int
    n3: int
    n4: int
    n5: int
    s1: int
    s2: int


# Source date typos verified against FDJ's official historical downloads:
# https://www.fdj.fr/jeux-de-tirage/euromillions-my-million/historique
# Match every number as well as the erroneous date so these repairs cannot
# accidentally alter another draw if the publisher changes its archive.
HISTORICAL_DATE_CORRECTIONS = {
    ("2099-11-20", (5, 9, 28, 43, 47, 2, 9)): "2009-11-20",
    ("2009-03-26", (8, 16, 18, 37, 43, 2, 6)): "2010-03-26",
    ("2010-07-04", (12, 13, 36, 41, 46, 1, 8)): "2010-07-02",
    ("2012-09-12", (6, 15, 22, 37, 44, 2, 4)): "2012-09-11",
    ("2012-12-16", (3, 7, 12, 13, 25, 5, 8)): "2014-12-16",
    ("2017-08-06", (29, 30, 36, 40, 41, 2, 9)): "2017-08-04",
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_draw(draw: Draw) -> tuple[bool, str]:
    """
    Validate a draw against EuroMillions rules.

    Returns (is_valid, error_message). error_message is empty when valid.
    """
    valid, reason = validate_iso_date(draw.date, first_date=date(2004, 2, 13))
    if not valid:
        return valid, reason
    numbers = [draw.n1, draw.n2, draw.n3, draw.n4, draw.n5]
    stars = [draw.s1, draw.s2]

    if len(set(numbers)) != 5:
        return False, f"duplicate main numbers: {numbers}"
    if not all(NUMBER_MIN <= n <= NUMBER_MAX for n in numbers):
        out = [n for n in numbers if not NUMBER_MIN <= n <= NUMBER_MAX]
        return False, f"main numbers out of range {NUMBER_MIN}-{NUMBER_MAX}: {out}"
    if len(set(stars)) != 2:
        return False, f"duplicate star numbers: {stars}"
    star_max = 9 if draw.date < "2011-05-10" else 11 if draw.date < "2016-09-27" else STAR_MAX
    if not all(STAR_MIN <= s <= star_max for s in stars):
        out = [s for s in stars if not STAR_MIN <= s <= star_max]
        return False, f"star numbers out of range {STAR_MIN}-{star_max} on {draw.date}: {out}"
    return True, ""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4})(?!\d)")


def _parse_date(raw: str) -> str | None:
    """Parse a date string like 'Fr. 03.01.2025' or '13.02.2004' into 'YYYY-MM-DD'."""
    m = _DATE_RE.search(raw)
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _valid_draw_day(draw_date: str) -> bool:
    weekday = date.fromisoformat(draw_date).weekday()
    return weekday == 4 or (draw_date >= "2011-05-10" and weekday == 1)


def parse_yearly_file(content: str, *, strict: bool = False) -> list[Draw]:
    """
    Parse a yearly CSV from win2day.at (2017–present).

    Format (semicolon-delimited):
      Ziehungstag;Zahl1;Zahl2;Zahl3;Zahl4;Zahl5;Stern1;Stern2;...
      Fr. 03.01.2025;3;19;29;35;37;1;9;...

    Rows with an empty first column are prize detail rows and are skipped.
    """
    draws: list[Draw] = []
    reader = csv.reader(io.StringIO(content), delimiter=";")
    header_found = False

    for row in reader:
        if not row:
            continue
        if not header_found:
            if row[0].strip().lstrip("\ufeff") == "Ziehungstag":
                header_found = True
            continue

        date_raw = row[0].strip()
        if not date_raw:
            continue  # prize detail row

        draw_date = _parse_date(date_raw)
        if not draw_date:
            report_parse_issue(f"invalid draw date: {date_raw!r}", strict=strict)
            continue

        try:
            numbers = sorted(int(row[i]) for i in range(1, 6))
            stars = sorted(int(row[i]) for i in range(6, 8))
        except (IndexError, ValueError) as e:
            report_parse_issue(
                f"could not parse numbers for {date_raw}: {e}", strict=strict,
            )
            continue

        draw = Draw(draw_date, *numbers, *stars)
        valid, reason = validate_draw(draw)
        if not valid:
            report_parse_issue(
                f"invalid draw {draw.date}: {reason}", strict=strict,
            )
            continue

        if strict and not _valid_draw_day(draw.date):
            raise ValueError(f"unexpected EuroMillions draw weekday: {draw.date}")
        draws.append(draw)

    if not header_found and strict:
        raise ValueError("missing EuroMillions yearly CSV header")
    return draws


def parse_historical_file(content: str, *, strict: bool = False) -> list[Draw]:
    """
    Parse the historical CSV (2004–2017) from win2day.at.

    The file uses a sideways layout with two draws per block.
    Each block starts with "Ergebnisse:" in column 1 and/or 13. Both sides
    have independent date slots (columns 11 and 23); some blocks contain only
    the right draw. One source cell stores an Excel serial date.

    The ascending-order numbers follow immediately after the first label row:
      Draw 1: main numbers at columns [1:6], stars at columns [6:8]
      Draw 2: main numbers at columns [13:18], stars at columns [18:20]
    """
    draws: list[Draw] = []
    rows = list(csv.reader(io.StringIO(content), delimiter=";"))
    for index, row in enumerate(rows):
        if not any(len(row) > offset and row[offset].strip() == "Ergebnisse:" for offset in (1, 13)):
            continue
        if index + 2 >= len(rows) or not any(
            "aufsteigende Reihenfolge" in cell for cell in rows[index + 1]
        ):
            report_parse_issue(f"historical block at row {index + 1} lacks its number rows", strict=strict)
            continue
        # Never scan into another block when this one is truncated or corrupt.
        num_row = rows[index + 2]
        for main_start, date_index in ((1, 11), (13, 23)):
            raw_date = row[date_index].strip() if len(row) > date_index else ""
            number_cells = num_row[main_start:main_start + 7]
            if not raw_date and not any(cell.strip() for cell in number_cells):
                continue
            draw_date = _parse_date(raw_date)
            if draw_date is None and re.fullmatch(r"\d{5}", raw_date):
                draw_date = (date(1899, 12, 30) + timedelta(days=int(raw_date))).isoformat()
            if draw_date is None:
                report_parse_issue(f"invalid historical date at row {index + 1}: {raw_date!r}", strict=strict)
                continue
            try:
                if len(number_cells) != 7:
                    raise ValueError("expected five main numbers and two stars")
                numbers = sorted(int(cell) for cell in number_cells[:5])
                stars = sorted(int(cell) for cell in number_cells[5:])
            except ValueError as exc:
                report_parse_issue(f"invalid numbers for {draw_date}: {exc}", strict=strict)
                continue
            values = tuple(numbers + stars)
            draw_date = HISTORICAL_DATE_CORRECTIONS.get((draw_date, values), draw_date)
            draw = Draw(draw_date, *values)
            valid, reason = validate_draw(draw)
            if not valid:
                report_parse_issue(f"invalid draw {draw.date}: {reason}", strict=strict)
                continue
            if strict and not _valid_draw_day(draw.date):
                raise ValueError(f"unexpected EuroMillions draw weekday: {draw.date}")
            draws.append(draw)

    return draws


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------

def load_existing_dates(csv_path: Path) -> set[str]:
    """Return the set of dates already stored in the results CSV."""
    return {draw.date for draw in load_existing_draws(csv_path)}


def load_existing_draws(csv_path: Path) -> list[Draw]:
    """Return all draws currently stored in the results CSV."""
    return read_draws(csv_path, Draw, validate_draw)


def write_draws(new_draws: list[Draw]) -> None:
    """Merge new draws into results.csv, sort by date, and write the full file."""
    write_draws_atomic(RESULTS_CSV, new_draws, Draw, validate_draw)


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_new_draws(init: bool = False) -> list[Draw]:
    """
    Download draw data and return only draws not yet in results.csv.

    init=True  — full import from 2004 to present
    init=False — resume a stale archive, covering at least the previous year;
                 automatically bootstrap an empty archive
    """
    existing_dates = load_existing_dates(RESULTS_CSV)
    today = date.today()
    all_new: list[Draw] = []

    full_history = init or not existing_dates or int(max(existing_dates)[:4]) < FIRST_YEARLY_YEAR
    if full_history:
        print("  Fetching historical data (2004–2016)...")
        content = fetch_url(HISTORICAL_URL)
        hist_draws = validate_source_draws(
            parse_historical_file(content, strict=True), HISTORICAL_URL, today=today,
        )
        all_new.extend(hist_draws)
        time.sleep(0.5)

    first_year = FIRST_YEARLY_YEAR if full_history else min(today.year - 1, int(max(existing_dates)[:4]))
    years = range(max(FIRST_YEARLY_YEAR, first_year), today.year + 1)

    for year in years:
        print(f"  Fetching year {year}...")
        url = YEARLY_URL.format(year=year)
        not_started = year == today.year and today.month == 1 and today.day <= 4
        try:
            content = fetch_url(url)
        except HTTPError as e:
            if e.response is not None and e.response.status_code == 404 and not_started:
                print(f"  Skipping {year}: file not yet available.")
                continue
            else:
                raise
        year_draws = validate_source_draws(
            parse_yearly_file(content, strict=True), url, year=year,
            allow_empty=not_started, today=today,
        )
        all_new.extend(year_draws)
        if full_history:
            time.sleep(0.5)

    return [draw for draw in validate_source_draws(all_new, "EuroMillions sources", today=today)
            if draw.date not in existing_dates]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Update the EuroMillions archive.")
    parser.add_argument("--init", action="store_true", help="fetch the complete history")
    parser.add_argument("--commit", action="store_true", help="commit changes to this archive")
    args = parser.parse_args()
    init, commit = args.init, args.commit

    print("Fetching EuroMillions...")

    try:
        new_draws = fetch_new_draws(init=init)
    except Exception as exc:
        print(f"  Fetch failed: {exc}", file=sys.stderr)
        return -1

    if new_draws:
        print(f"  {len(new_draws)} new draw(s) found:")
        for draw in new_draws:
            print(
                f"    {draw.date}: {draw.n1},{draw.n2},{draw.n3},"
                f"{draw.n4},{draw.n5} S:{draw.s1},{draw.s2}"
            )
        try:
            write_draws(new_draws)
        except (OSError, ValueError) as exc:
            print(f"  Write failed: {exc}", file=sys.stderr)
            return -1

    else:
        print("  No new draws found.")

    if commit and RESULTS_CSV.exists():
        message = "Update EU EuroMillions results"
        if new_draws:
            message += ": " + ", ".join(d.date for d in new_draws)
        try:
            if git_commit(str(RESULTS_CSV), message):
                print(f"  Committed: {message}")
        except Exception as exc:
            print(f"  Commit failed: {exc}", file=sys.stderr)
            return -1

    return len(new_draws)


if __name__ == "__main__":
    sys.exit(0 if main() >= 0 else 1)
