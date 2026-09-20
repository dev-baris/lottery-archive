#!/usr/bin/env python3
"""
Fetch German Lotto 6 aus 49 results from lottozahlenonline.de.

Scrapes the combined (both draw days) archive page, one year at a time:
  https://www.lottozahlenonline.de/statistik/beide-spieltage/lottozahlen-archiv.php?j=YYYY

This archive retains draws from 2000-01-01 onward. That is the project's
coverage policy, not the game's first draw date. Every retained draw must
include its Superzahl (digit 0–9).

Usage:
  python fetch_lotto_de_6aus49.py            # fetch current + previous year
  python fetch_lotto_de_6aus49.py --init     # full archive import (2000 to present)
  python fetch_lotto_de_6aus49.py --commit   # fetch and git-commit if new data found
"""

import argparse
import sys
import time
from bs4 import BeautifulSoup
from datetime import date
from pathlib import Path
from typing import NamedTuple

from archive_policy import LOTTO_FIRST_YEAR, validate_lotto_archive_date
from archive_utils import (
    read_draws, report_parse_issue, validate_source_draws,
    write_draws_atomic,
)
from git_utils import git_commit
from http_utils import fetch_url

RESULTS_CSV = Path(__file__).parent.parent / "de" / "lotto_6aus49" / "results.csv"
BASE_URL = (
    "https://www.lottozahlenonline.de/statistik/beide-spieltage"
    "/lottozahlen-archiv.php"
)
FIRST_YEAR = LOTTO_FIRST_YEAR

NUMBER_MIN, NUMBER_MAX = 1, 49
SUPERZAHL_MIN, SUPERZAHL_MAX = 0, 9


class Draw(NamedTuple):
    date: str           # ISO format: YYYY-MM-DD
    n1: int
    n2: int
    n3: int
    n4: int
    n5: int
    n6: int
    superzahl: int | None   # None represents an invalid, missing source value


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_draw(draw: Draw) -> tuple[bool, str]:
    """
    Validate a draw against DE Lotto 6 aus 49 rules and archive coverage.

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
    if draw.superzahl is None:
        return False, "missing superzahl: required for every archived draw"
    if not (SUPERZAHL_MIN <= draw.superzahl <= SUPERZAHL_MAX):
        return False, (
            f"superzahl {draw.superzahl} out of range "
            f"{SUPERZAHL_MIN}-{SUPERZAHL_MAX}"
        )
    return True, ""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_year_page(html: str, *, strict: bool = False) -> list[Draw]:
    """
    Parse one year-page from lottozahlenonline.de.

    Each draw row is a ``div.zahlensuche_rahmen`` containing:
      - ``time.zahlensuche_datum[datetime]``  — ISO date (YYYY-MM-DD)
      - ``div.zahlensuche_zahl`` (×6)         — main numbers 1–49
      - ``div.zahlensuche_zz``                — Superzahl 0–9
    """
    soup = BeautifulSoup(html, "lxml")
    draws: list[Draw] = []

    for row in soup.find_all("div", class_="zahlensuche_rahmen"):
        time_tag = row.find("time", class_="zahlensuche_datum")
        if not time_tag:
            report_parse_issue("draw row has no date element", strict=strict)
            continue
        draw_date = time_tag.get("datetime", "").strip()
        if not draw_date:
            report_parse_issue("draw row has no datetime value", strict=strict)
            continue

        number_divs = row.find_all("div", class_="zahlensuche_zahl")
        if len(number_divs) != 6:
            report_parse_issue(
                f"expected 6 numbers, got {len(number_divs)} for {draw_date}",
                strict=strict,
            )
            continue

        sz_div = row.find("div", class_="zahlensuche_zz")
        sz_text = sz_div.get_text(strip=True) if sz_div else ""

        try:
            numbers = sorted(int(d.get_text(strip=True)) for d in number_divs)
            superzahl: int | None = int(sz_text) if sz_text else None
        except ValueError as e:
            report_parse_issue(
                f"could not parse numbers for {draw_date}: {e}", strict=strict,
            )
            continue

        draw = Draw(draw_date, *numbers, superzahl)
        valid, reason = validate_draw(draw)
        if not valid:
            report_parse_issue(
                f"invalid draw {draw.date}: {reason}", strict=strict,
            )
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
    return read_draws(csv_path, Draw, validate_draw, nullable_fields=frozenset({"superzahl"}))


def write_draws(new_draws: list[Draw]) -> None:
    """Merge new draws into results.csv, sort by date, and write the full file."""
    write_draws_atomic(
        RESULTS_CSV, new_draws, Draw, validate_draw,
        nullable_fields=frozenset({"superzahl"}),
    )


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_year(year: int, existing_dates: set[str]) -> list[Draw]:
    """Fetch all draws for one calendar year and return those not yet stored."""
    today = date.today()
    if isinstance(year, bool) or not isinstance(year, int) or not FIRST_YEAR <= year <= today.year:
        raise ValueError(f"year must be an integer between {FIRST_YEAR} and {today.year}")
    url = f"{BASE_URL}?j={year}"
    html = fetch_url(url)
    not_started = year == today.year and today.month == 1 and today.day <= 3
    all_draws = validate_source_draws(
        parse_year_page(html, strict=True), url, year=year,
        allow_empty=not_started and "zahlensuche" in html, today=today,
    )
    return [d for d in all_draws if d.date not in existing_dates]


def fetch_new_draws(init: bool = False) -> list[Draw]:
    """
    Download draw data and return only draws not yet in results.csv.

    init=True  — full import from the archive's first year (2000) to present
    init=False — resume a stale archive, covering at least the previous year;
                 automatically bootstrap an empty archive
    """
    existing_dates = load_existing_dates(RESULTS_CSV)
    today = date.today()

    full_history = init or not existing_dates
    first_year = FIRST_YEAR if full_history else max(
        FIRST_YEAR, min(today.year - 1, int(max(existing_dates)[:4])),
    )
    years = range(first_year, today.year + 1)

    all_new: list[Draw] = []
    for year in years:
        print(f"  Fetching year {year}...")
        new = fetch_year(year, existing_dates)
        all_new.extend(new)
        existing_dates.update(d.date for d in new)
        if full_history:
            time.sleep(0.5)     # polite delay during bulk import

    return sorted(all_new, key=lambda d: d.date)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Update the German Lotto 6 aus 49 archive.")
    parser.add_argument("--init", action="store_true", help=f"fetch all draws since {FIRST_YEAR}")
    parser.add_argument("--commit", action="store_true", help="commit changes to this archive")
    args = parser.parse_args()
    init, commit = args.init, args.commit

    print("Fetching DE Lotto 6 aus 49...")

    try:
        new_draws = fetch_new_draws(init=init)
    except Exception as exc:
        print(f"  Fetch failed: {exc}", file=sys.stderr)
        return -1

    if new_draws:
        print(f"  {len(new_draws)} new draw(s) found:")
        for draw in new_draws:
            print(f"    {draw.date}: {draw.n1},{draw.n2},{draw.n3},"
                  f"{draw.n4},{draw.n5},{draw.n6} SZ:{draw.superzahl}")
        try:
            write_draws(new_draws)
        except (OSError, ValueError) as exc:
            print(f"  Write failed: {exc}", file=sys.stderr)
            return -1

    else:
        print("  No new draws found.")

    if commit and RESULTS_CSV.exists():
        message = "Update DE Lotto 6 aus 49 results"
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
