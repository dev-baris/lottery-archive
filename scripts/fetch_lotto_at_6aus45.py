#!/usr/bin/env python3
"""
Fetch Austrian Lotto 6 aus 45 results since 2000 from win2day.at.

Sources:
  - Historical 1986-2010: statics.win2day.at/media-nopagespeed/lotto-ergebnisse-1986-2010.csv
  - Historical 2010-2017: statics.win2day.at/media-nopagespeed/lotto-ziehungen-2010-2017.csv
  - Yearly 2018+:         statics.win2day.at/media/NN_W2D_STAT_Lotto_{YEAR}.csv

Usage:
  python fetch_lotto_at_6aus45.py                    # fetch recent draws
  python fetch_lotto_at_6aus45.py --init             # fetch history from 2000 to present
  python fetch_lotto_at_6aus45.py --commit           # fetch and git-commit if new data found
  python fetch_lotto_at_6aus45.py --init --commit    # full history + commit
"""

import argparse
import csv
import re
import sys
from datetime import date
from io import StringIO
from pathlib import Path
from typing import NamedTuple

from archive_policy import LOTTO_FIRST_YEAR, validate_lotto_archive_date
from archive_utils import (
    read_draws, report_parse_issue, validate_source_draws,
    write_draws_atomic,
)
from git_utils import git_commit
from http_utils import fetch_url, HTTPError

RESULTS_CSV = Path(__file__).parent.parent / "at" / "lotto_6aus45" / "results.csv"
YEARLY_BASE_URL = "https://statics.win2day.at/media/NN_W2D_STAT_Lotto_{year}.csv"
HISTORICAL_URLS = [
    "https://statics.win2day.at/media-nopagespeed/lotto-ergebnisse-1986-2010.csv",
    "https://statics.win2day.at/media-nopagespeed/lotto-ziehungen-2010-2017.csv",
]
YEARLY_START = 2018

WEEKDAYS = {"Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"}
YEAR_HEADER_RE = re.compile(r"^(\d{4})\s+Lotto", re.IGNORECASE)

# Valid number ranges for AT Lotto 6 aus 45
NUMBER_MIN, NUMBER_MAX = 1, 45
ZUSATZZAHL_MIN, ZUSATZZAHL_MAX = 1, 45


class Draw(NamedTuple):
    date: str       # ISO format: YYYY-MM-DD
    n1: int
    n2: int
    n3: int
    n4: int
    n5: int
    n6: int
    zusatzzahl: int


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_draw(draw: Draw) -> tuple[bool, str]:
    """
    Validate a draw against AT Lotto 6 aus 45 rules.

    Returns (is_valid, error_message). error_message is empty when valid.
    """
    valid, reason = validate_lotto_archive_date(draw.date)
    if not valid:
        return valid, reason
    numbers = [draw.n1, draw.n2, draw.n3, draw.n4, draw.n5, draw.n6]

    if len(set(numbers)) != 6:
        return False, f"duplicate numbers: {numbers}"
    if not all(NUMBER_MIN <= n <= NUMBER_MAX for n in numbers):
        out = [n for n in numbers if not NUMBER_MIN <= n <= NUMBER_MAX]
        return False, f"numbers out of range {NUMBER_MIN}-{NUMBER_MAX}: {out}"
    if not (ZUSATZZAHL_MIN <= draw.zusatzzahl <= ZUSATZZAHL_MAX):
        return False, (
            f"zusatzzahl {draw.zusatzzahl} out of range "
            f"{ZUSATZZAHL_MIN}-{ZUSATZZAHL_MAX}"
        )
    if draw.zusatzzahl in numbers:
        return False, f"zusatzzahl {draw.zusatzzahl} duplicates a main number"
    return True, ""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_date_str(date_str: str, year: int) -> date | None:
    """Parse a 'DD.M.' or 'DD.MM.' date string using the given year."""
    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(?:(\d{4}))?", date_str.strip())
    if not match:
        return None
    try:
        if match.group(3) is not None and int(match.group(3)) != year:
            return None
        return date(year, int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


def parse_yearly_file(content: str, year: int, *, strict: bool = False) -> list[Draw]:
    """
    Parse the modern yearly CSV format used from 2018 onwards.

    Format (semicolon-separated):
        Datum;Reihenfolge;Zahl1;Zahl2;Zahl3;Zahl4;Zahl5;Zahl6;ZZ;Zusatzzahl;...
        04.01.;aufsteigend;1;4;15;16;22;38;ZZ;11;...
        04.01.;;;;;;;;;;...   <- second row per draw (prize tiers, skipped)

    Only rows with Reihenfolge == 'aufsteigend' contain draw numbers.
    Years before the archive's 2000 cutoff are rejected.
    """
    if year < LOTTO_FIRST_YEAR:
        raise ValueError(f"requested year {year} precedes archive start {LOTTO_FIRST_YEAR}")
    draws: list[Draw] = []
    reader = csv.reader(StringIO(content), delimiter=";")
    header_found = False

    for row in reader:
        if not row or not row[0].strip():
            continue
        if not header_found:
            if row[0].strip().lstrip("\ufeff") == "Datum":
                header_found = True
            continue
        if len(row) < 2 or not row[1].strip():
            continue
        if row[1].strip() != "aufsteigend":
            if row[1].strip() != "gezogen":
                report_parse_issue(f"unrecognized draw order on {row[0]}: {row[1]!r}", strict=strict)
            continue

        draw_date = parse_date_str(row[0], year)
        if draw_date is None:
            report_parse_issue(f"invalid draw date for {year}: {row[0]!r}", strict=strict)
            continue

        try:
            numbers = sorted(int(row[i]) for i in range(2, 8))
            zusatzzahl = int(row[9])
        except (ValueError, IndexError) as exc:
            report_parse_issue(f"invalid numbers for {draw_date}: {exc}", strict=strict)
            continue

        draw = Draw(draw_date.isoformat(), *numbers, zusatzzahl)
        valid, reason = validate_draw(draw)
        if not valid:
            report_parse_issue(f"invalid draw {draw.date}: {reason}", strict=strict)
            continue

        draws.append(draw)

    if not header_found and strict:
        raise ValueError(f"missing Lotto CSV header for {year}")
    return draws


def parse_historical_file(content: str, *, strict: bool = False) -> list[Draw]:
    """
    Parse eligible draws from the historical CSVs (1986-2010, 2010-2017).

    Year header lines like '2010 Lotto - Beträge in EUR' mark year boundaries.
    Sections before 2000 are outside the archive scope and are skipped before
    their draw rows are parsed; eligible rows retain strict source validation.

    Two column layouts are used:
      Format A (2010-2017): Weekday; Date; "aufsteigend"; N1-N6; "Zz"; Zusatzzahl; ...
      Format B (1986-2010): Weekday.; Date; N1-N6; "Zz:"; Zusatzzahl; ...
    """
    draws: list[Draw] = []
    current_year: int | None = None
    reader = csv.reader(StringIO(content), delimiter=";")

    for row in reader:
        if not row:
            continue
        first = row[0].strip().lstrip("\ufeff")

        match = YEAR_HEADER_RE.match(first)
        if match:
            current_year = int(match.group(1))
            continue
        if current_year is None or current_year < LOTTO_FIRST_YEAR:
            continue

        # Normalise weekday: both "So" (2010-2017) and "So." (1986-2010) are valid
        weekday = first.rstrip(".")
        if weekday not in WEEKDAYS:
            continue

        order = row[2].strip() if len(row) > 2 else ""

        # The official archive includes cancellation/postponement notices in
        # place of draw numbers (1986-12-28 and 1998-12-23). These describe
        # non-draws, and must not be mistaken for corrupt result rows.
        if not any(cell.strip() for cell in row[3:10]) and (
            "".join(order.split()).casefold() == "entfallen"
            or re.fullmatch(r"Ziehung wurde auf den \d{1,2}\.\d{1,2}\.\d{4} verschoben", order)
        ):
            continue

        if order == "aufsteigend" and len(row) >= 11:
            # Format A (2010-2017)
            draw_date = parse_date_str(row[1], current_year)
            try:
                numbers = sorted(int(row[i]) for i in range(3, 9))
                zusatzzahl = int(row[10])
            except (ValueError, IndexError) as exc:
                report_parse_issue(f"invalid numbers for {row[1]!r} in {current_year}: {exc}", strict=strict)
                continue
        elif len(row) >= 10:
            # Format B (1986-2010): N1-N6 start at column 2, Zusatzzahl at column 9
            draw_date = parse_date_str(row[1], current_year)
            try:
                numbers = sorted(int(row[i]) for i in range(2, 8))
                zusatzzahl = int(row[9])
            except (ValueError, IndexError) as exc:
                report_parse_issue(f"invalid numbers for {row[1]!r} in {current_year}: {exc}", strict=strict)
                continue
        else:
            report_parse_issue(f"incomplete historical draw row: {row!r}", strict=strict)
            continue

        if draw_date is None:
            report_parse_issue(f"invalid draw date for {current_year}: {row[1]!r}", strict=strict)
            continue

        draw = Draw(draw_date.isoformat(), *numbers, zusatzzahl)
        valid, reason = validate_draw(draw)
        if not valid:
            report_parse_issue(f"invalid draw {draw.date}: {reason}", strict=strict)
            continue

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


def fetch_new_draws(init: bool = False) -> list[Draw]:
    """
    Fetch draws from win2day.at and return only those not yet in results.csv.

    Args:
        init: If True, download the supported history from 2000. An empty archive is
              bootstrapped automatically; stale archives resume at their last
              stored year, with at least the current and previous year fetched.
    """
    today = date.today()
    current_year = today.year
    existing_dates = load_existing_dates(RESULTS_CSV)
    all_draws: list[Draw] = []

    full_history = init or not existing_dates or int(max(existing_dates)[:4]) < YEARLY_START
    if full_history:
        for url in HISTORICAL_URLS:
            print(f"  Fetching historical file: {url}")
            content = fetch_url(url)
            all_draws.extend(validate_source_draws(
                parse_historical_file(content, strict=True), url, today=today,
            ))
        years = range(YEARLY_START, current_year + 1)
    else:
        first_year = min(current_year - 1, int(max(existing_dates)[:4]))
        years = range(max(YEARLY_START, first_year), current_year + 1)

    for year in years:
        url = YEARLY_BASE_URL.format(year=year)
        print(f"  Fetching yearly file: {url}")
        not_started = year == current_year and today.month == 1 and today.day <= 7
        try:
            content = fetch_url(url)
        except HTTPError as e:
            if e.response is not None and e.response.status_code == 404 and not_started:
                print(f"  Skipping {year}: file not yet available.")
                continue
            else:
                raise
        all_draws.extend(validate_source_draws(
            parse_yearly_file(content, year, strict=True), url,
            year=year, allow_empty=not_started, today=today,
        ))

    seen: set[str] = set()
    new_draws: list[Draw] = []
    for draw in validate_source_draws(all_draws, "AT Lotto sources", today=today):
        if draw.date in seen or draw.date in existing_dates:
            continue
        seen.add(draw.date)
        new_draws.append(draw)

    return new_draws


def write_draws(new_draws: list[Draw]) -> None:
    """Merge new draws into results.csv, sort by date, and write the full file."""
    write_draws_atomic(RESULTS_CSV, new_draws, Draw, validate_draw)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Update the Austrian Lotto 6 aus 45 archive.")
    parser.add_argument(
        "--init", action="store_true",
        help=f"fetch the complete history since {LOTTO_FIRST_YEAR}",
    )
    parser.add_argument("--commit", action="store_true", help="commit changes to this archive")
    args = parser.parse_args()
    init, commit = args.init, args.commit
    mode = "full history" if init else "recent update"
    print(f"Fetching AT Lotto 6 aus 45 ({mode})...")

    try:
        new_draws = fetch_new_draws(init=init)
    except Exception as exc:
        print(f"  Fetch failed: {exc}", file=sys.stderr)
        return -1

    if new_draws:
        print(f"  {len(new_draws)} new draw(s) found:")
        for draw in new_draws:
            print(f"    {draw.date}: {draw.n1},{draw.n2},{draw.n3},"
                  f"{draw.n4},{draw.n5},{draw.n6} ZZ:{draw.zusatzzahl}")
        try:
            write_draws(new_draws)
        except (OSError, ValueError) as exc:
            print(f"  Write failed: {exc}", file=sys.stderr)
            return -1

    else:
        print("  No new draws found.")

    if commit and RESULTS_CSV.exists():
        message = "Update AT Lotto 6 aus 45 results"
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
