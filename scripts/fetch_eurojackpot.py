#!/usr/bin/env python3
"""Collect Eurojackpot's complete annual archives from 2012 onward.

The source's ``time[datetime]`` attributes contain YYYY-DD-MM, so parse the
visible German dates instead. No partial year is written after a fetch or
validation failure. An empty local archive bootstraps the complete history.
"""

import argparse
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import NamedTuple

from bs4 import BeautifulSoup

from archive_utils import read_draws, validate_iso_date, write_draws_atomic
from git_utils import git_commit
from http_utils import fetch_url

RESULTS_CSV = Path(__file__).resolve().parent.parent / "eu" / "eurojackpot" / "results.csv"
ARCHIVE_URL = "https://www.eurojackpot-zahlen.eu/eurojackpot-zahlenarchiv.php"
FIRST_YEAR = 2012
FIRST_DRAW = date(2012, 3, 23)
EURO_10_START = date(2014, 10, 10)
EURO_12_START = date(2022, 3, 25)
TUESDAY_START = date(2022, 3, 29)
_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


class Draw(NamedTuple):
    date: str
    n1: int
    n2: int
    n3: int
    n4: int
    n5: int
    e1: int
    e2: int


def euro_number_max(draw_date: date) -> int:
    """Return the Euro-number pool used on this draw date."""
    if draw_date < EURO_10_START:
        return 8
    return 10 if draw_date < EURO_12_START else 12


def is_draw_date(day: date) -> bool:
    return day >= FIRST_DRAW and (
        day.weekday() == 4 or (day >= TUESDAY_START and day.weekday() == 1)
    )


def validate_draw(draw: Draw) -> tuple[bool, str]:
    valid, reason = validate_iso_date(draw.date, first_date=FIRST_DRAW)
    if not valid:
        return valid, reason
    day = date.fromisoformat(draw.date)
    if not is_draw_date(day):
        return False, f"not a scheduled Eurojackpot draw day: {draw.date}"
    numbers, euros = draw[1:6], draw[6:8]
    if len(set(numbers)) != 5:
        return False, f"duplicate main numbers: {numbers}"
    if not all(1 <= n <= 50 for n in numbers):
        return False, f"main numbers out of range 1-50: {numbers}"
    if len(set(euros)) != 2:
        return False, f"duplicate Euro numbers: {euros}"
    maximum = euro_number_max(day)
    if not all(1 <= n <= maximum for n in euros):
        return False, f"Euro numbers out of range 1-{maximum}: {euros}"
    if tuple(sorted(numbers)) != numbers or tuple(sorted(euros)) != euros:
        return False, "main numbers and Euro numbers must each be sorted ascending"
    return True, ""


def archive_url(year: int, *, current_year: int | None = None) -> str:
    """Use the bare URL for the live year and ?j=YYYY for every past year."""
    current_year = date.today().year if current_year is None else current_year
    if not FIRST_YEAR <= year <= current_year:
        raise ValueError(f"Year must be between {FIRST_YEAR} and {current_year}: {year}")
    return ARCHIVE_URL if year == current_year else f"{ARCHIVE_URL}?j={year}"


def expected_draw_dates(year: int, *, through: date) -> set[str]:
    """Scheduled draws in a year, truncated at the supplied inclusive date."""
    day = max(date(year, 1, 1), FIRST_DRAW)
    end = min(date(year, 12, 31), through)
    expected: set[str] = set()
    while day <= end:
        if is_draw_date(day):
            expected.add(day.isoformat())
        day += timedelta(days=1)
    return expected


def parse_year(
    html: str,
    year: int,
    *,
    reference_date: date | None = None,
) -> list[Draw]:
    """Parse and validate one complete published annual archive.

    Require every scheduled draw through yesterday (or December 31 for past
    years). A draw scheduled today can still be awaiting publication. Validate
    the heading too, so a year URL silently serving another year is an error.
    """
    today = reference_date or date.today()
    archive_url(year, current_year=today.year)  # validate the requested year
    soup = BeautifulSoup(html, "lxml")
    archive = soup.select_one("#gewinnzahlen")
    if archive is None:
        raise ValueError(f"{year}: Eurojackpot archive container is missing")
    heading = archive.find(["h2", "h3"])
    if heading is None or not re.search(rf"\b{year}\b", heading.get_text(" ", strip=True)):
        raise ValueError(f"{year}: archive heading is missing or reports another year")

    draws: dict[str, Draw] = {}
    for row in archive.select(".zahlen_rahmen"):
        day_nodes = row.select(".zahlenarchiv_datum")
        main_nodes = row.select(".zahlenarchiv_zahl")
        euro_nodes = row.select(".zahlenarchiv_zz")
        if not day_nodes and not main_nodes and not euro_nodes and row.select(".zahlen_hinweis02"):
            continue  # the column heading is the only recognized non-draw row
        if len(day_nodes) != 1 or len(main_nodes) != 5 or len(euro_nodes) != 2:
            raise ValueError(f"{year}: malformed archive row (expected a date and 5 + 2 numbers)")
        raw_date = day_nodes[0].get_text(strip=True)
        match = _DATE_RE.fullmatch(raw_date)
        if match is None:
            raise ValueError(f"{year}: malformed visible draw date: {raw_date!r}")
        day, month, draw_year = map(int, match.groups())
        try:
            parsed_date = date(draw_year, month, day)
        except ValueError as exc:
            raise ValueError(f"{year}: invalid calendar date: {raw_date!r}") from exc
        if parsed_date.year != year:
            raise ValueError(f"{year}: unexpected draw year in {raw_date}")
        if parsed_date > today:
            raise ValueError(f"{year}: future draw in source: {raw_date}")
        try:
            main_numbers = sorted(int(node.get_text(strip=True)) for node in main_nodes)
            euro_numbers = sorted(int(node.get_text(strip=True)) for node in euro_nodes)
        except ValueError as exc:
            raise ValueError(f"{raw_date}: invalid draw numbers") from exc
        draw = Draw(parsed_date.isoformat(), *main_numbers, *euro_numbers)
        valid, reason = validate_draw(draw)
        if not valid:
            raise ValueError(f"{draw.date}: {reason}")
        if draw.date in draws:
            raise ValueError(f"{year}: duplicate draw date in source: {draw.date}")
        draws[draw.date] = draw

    missing = expected_draw_dates(year, through=today - timedelta(days=1)) - draws.keys()
    if missing:
        sample = ", ".join(sorted(missing)[:5])
        raise ValueError(f"{year}: archive is incomplete; {len(missing)} missing draw(s): {sample}")
    return sorted(draws.values(), key=lambda draw: draw.date)


def load_existing_draws(csv_path: Path) -> list[Draw]:
    return read_draws(csv_path, Draw, validate_draw)


def load_existing_dates(csv_path: Path) -> set[str]:
    return {draw.date for draw in load_existing_draws(csv_path)}


def write_draws(new_draws: list[Draw]) -> None:
    write_draws_atomic(RESULTS_CSV, new_draws, Draw, validate_draw)


def fetch_new_draws(
    init: bool = False,
    *,
    start_year: int | None = None,
    end_year: int | None = None,
) -> list[Draw]:
    """Fetch requested years and return new or corrected draws, without writing.

    Regular updates fetch the previous and current years, plus any earlier
    year with missing scheduled draws. A missing or empty archive bootstraps
    from 2012. --init rechecks every year for corrections too. Explicit year
    bounds provide repeatable imports without hardcoding the live year.
    """
    today = date.today()
    if init and (start_year is not None or end_year is not None):
        raise ValueError("--init cannot be combined with explicit year bounds")
    end = today.year if end_year is None else end_year
    start = start_year
    existing = {draw.date: draw for draw in load_existing_draws(RESULTS_CSV)}
    if start is None:
        start = FIRST_YEAR if init or not existing else max(FIRST_YEAR, end - 1)
        if not init and existing and end_year is None:
            # Repair interrupted/partial imports and archives left idle for
            # several years. Do not require a user to notice a hidden gap.
            for year in range(FIRST_YEAR, start):
                expected = expected_draw_dates(year, through=date(year, 12, 31))
                if expected - existing.keys():
                    start = year
                    break
    archive_url(start, current_year=today.year)
    archive_url(end, current_year=today.year)
    if start > end:
        raise ValueError("--start-year must not exceed --end-year")

    changed: list[Draw] = []
    for year in range(start, end + 1):
        url = archive_url(year, current_year=today.year)
        print(f"  Fetching Eurojackpot {year}: {url}")
        draws = parse_year(fetch_url(url), year, reference_date=today)
        changed.extend(draw for draw in draws if existing.get(draw.date) != draw)
        if year < end:
            time.sleep(0.5)
    return sorted(changed, key=lambda draw: draw.date)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init", action="store_true", help="recheck all years from 2012 onward")
    parser.add_argument("--start-year", type=int, help="first year to fetch, inclusive")
    parser.add_argument("--end-year", type=int, help="last year to fetch, inclusive (default: current year)")
    parser.add_argument("--commit", action="store_true", help="commit only the updated Eurojackpot CSV")
    args = parser.parse_args(argv)
    if args.init and (args.start_year is not None or args.end_year is not None):
        parser.error("--init cannot be combined with --start-year or --end-year")

    try:
        draws = fetch_new_draws(args.init, start_year=args.start_year, end_year=args.end_year)
        if draws:
            write_draws(draws)
            print(f"Eurojackpot: wrote {len(draws)} new or corrected draw(s), {draws[0].date}–{draws[-1].date}.")
        else:
            print("Eurojackpot: archive is already up to date.")
        if args.commit and RESULTS_CSV.exists():
            # Retry a prior successful write whose commit failed, even when
            # the source has no newer draw on this invocation.
            message = "Update EU Eurojackpot results"
            if draws:
                message += f": {len(draws)} draw(s), {draws[0].date} to {draws[-1].date}"
            git_commit(str(RESULTS_CSV), message)
        return len(draws)
    except Exception as exc:
        print(f"Eurojackpot update failed: {exc}", file=sys.stderr)
        return -1


if __name__ == "__main__":
    sys.exit(0 if main() >= 0 else 1)
