#!/usr/bin/env python3
"""Validate archive CSV schemas, draw numbers, chronology, and freshness.

Run without filters to check every game. ``--country at|de|eu`` retains the
original selectors (``eu`` means EuroMillions); ``--game eurojackpot`` selects
the new archive. ``--skip-stale`` is intended for offline historical checks.
"""

import argparse
import csv
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from archive_policy import LOTTO_FIRST_DATE

REPO_ROOT = Path(__file__).resolve().parent.parent
AT_CSV = REPO_ROOT / "at" / "lotto_6aus45" / "results.csv"
DE_CSV = REPO_ROOT / "de" / "lotto_6aus49" / "results.csv"
EU_CSV = REPO_ROOT / "eu" / "euromillions" / "results.csv"
EUROJACKPOT_CSV = REPO_ROOT / "eu" / "eurojackpot" / "results.csv"


@dataclass
class GameRules:
    label: str
    csv_path: Path
    number_min: int
    number_max: int
    num_count: int
    extra_fields: list[str]
    extra_min: int
    extra_max: int
    max_stale_days: int = 7
    game_id: str = ""
    first_draw: date | None = None
    archive_start: date | None = None
    extras_required_from: date = date.min
    extras_separate_from_main: bool = False
    extra_max_changes: tuple[tuple[date, int], ...] = ()
    draw_weekdays: tuple[tuple[date, tuple[int, ...]], ...] = ()

    @property
    def fieldnames(self) -> list[str]:
        return ["date", *(f"n{i}" for i in range(1, self.num_count + 1)),
                *self.extra_fields]

    def extra_limit(self, draw_date: date) -> int:
        """Apply the pool size that was in force on the draw date."""
        limit = self.extra_max
        for effective_date, new_limit in self.extra_max_changes:
            if draw_date >= effective_date:
                limit = new_limit
        return limit

    def is_draw_day(self, draw_date: date) -> bool:
        weekdays: tuple[int, ...] = ()
        for effective_date, new_weekdays in self.draw_weekdays:
            if draw_date >= effective_date:
                weekdays = new_weekdays
        return draw_date.weekday() in weekdays


GAMES = [
    GameRules(
        label="AT Lotto 6 aus 45", game_id="at", csv_path=AT_CSV,
        number_min=1, number_max=45, num_count=6,
        extra_fields=["zusatzzahl"], extra_min=1, extra_max=45,
        first_draw=date(1986, 9, 7), extras_separate_from_main=True,
        archive_start=LOTTO_FIRST_DATE,
    ),
    GameRules(
        label="DE Lotto 6 aus 49", game_id="de", csv_path=DE_CSV,
        number_min=1, number_max=49, num_count=6,
        extra_fields=["superzahl"], extra_min=0, extra_max=9,
        first_draw=date(1955, 10, 9), extras_required_from=date(1991, 12, 7),
        archive_start=LOTTO_FIRST_DATE,
        # LOTTO Bayern's unified archive adds Wednesday draws from 2000-12-06:
        # https://www.lotto-bayern.de/lotto6aus49/gewinnzahlen
        draw_weekdays=((LOTTO_FIRST_DATE, (5,)), (date(2000, 12, 6), (2, 5))),
    ),
    GameRules(
        label="EU EuroMillions", game_id="euromillions", csv_path=EU_CSV,
        number_min=1, number_max=50, num_count=5,
        extra_fields=["s1", "s2"], extra_min=1, extra_max=9,
        first_draw=date(2004, 2, 13),
        extra_max_changes=((date(2011, 5, 10), 11), (date(2016, 9, 27), 12)),
        draw_weekdays=((date(2004, 2, 13), (4,)), (date(2011, 5, 10), (1, 4))),
    ),
    GameRules(
        label="EU Eurojackpot", game_id="eurojackpot", csv_path=EUROJACKPOT_CSV,
        number_min=1, number_max=50, num_count=5,
        extra_fields=["e1", "e2"], extra_min=1, extra_max=8,
        first_draw=date(2012, 3, 23),
        # WestLotto: /newsroom/wissenswertes-eurojackpot/
        # LOTTO.de: /eurojackpot/produktaenderung-2022
        extra_max_changes=((date(2014, 10, 10), 10), (date(2022, 3, 25), 12)),
        draw_weekdays=((date(2012, 3, 23), (4,)), (date(2022, 3, 29), (1, 4))),
    ),
]


def check_csv(rules: GameRules, reference_date: date | None = None,
              skip_stale: bool = False) -> tuple[list[str], int]:
    """Return actionable validation errors and the number of data records read.

    Schema or malformed-record errors are reported instead of raising obscure
    KeyError/TypeError exceptions. A future date never makes stale data look
    fresh. The German Lotto, EuroMillions, and Eurojackpot calendars also detect
    gaps between the earliest and latest recorded draws; this does not require
    partial exports to begin at the game's launch date. AT/DE records must also
    respect the archive's inclusive retention date, independently of each game's launch.
    """
    today = reference_date or date.today()
    try:
        with rules.csv_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle, strict=True)
            header = next(reader, None)
            records = [(reader.line_num, fields) for fields in reader]
    except FileNotFoundError:
        return [f"File not found: {rules.csv_path}"], 0
    except (OSError, UnicodeError, csv.Error) as exc:
        return [f"Could not read CSV {rules.csv_path}: {exc}"], 0

    errors: list[str] = []
    if header != rules.fieldnames:
        errors.append(f"Invalid CSV header: expected {rules.fieldnames}, got {header}.")
    if not records:
        errors.append("File is empty (no draw records).")
    if errors:
        return errors, len(records)

    dates: list[date] = []
    seen_dates: dict[date, int] = {}
    previous_date: date | None = None

    for line_number, fields in records:
        if len(fields) != len(header):
            errors.append(
                f"Row {line_number}: expected {len(header)} columns, got {len(fields)}."
            )
            continue
        row = dict(zip(header, fields, strict=True))
        raw_date = row["date"]
        try:
            draw_date = date.fromisoformat(raw_date)
            if draw_date.isoformat() != raw_date:
                raise ValueError("date must use YYYY-MM-DD")
        except ValueError:
            errors.append(f"Row {line_number}: invalid date '{raw_date}' (use YYYY-MM-DD)")
            continue

        prefix = f"Row {line_number} ({raw_date})"
        if draw_date in seen_dates:
            errors.append(
                f"{prefix}: duplicate date {raw_date} "
                f"(first seen in row {seen_dates[draw_date]})"
            )
        seen_dates.setdefault(draw_date, line_number)
        if previous_date is not None and draw_date < previous_date:
            errors.append(
                f"{prefix}: date is before previous {previous_date} "
                "(file is not sorted chronologically)"
            )
        previous_date = draw_date
        if draw_date > today:
            errors.append(f"{prefix}: future draw date (reference date is {today}).")
        else:
            dates.append(draw_date)
        if rules.first_draw is not None and draw_date < rules.first_draw:
            errors.append(f"{prefix}: date precedes first draw on {rules.first_draw}.")
        if rules.archive_start is not None and draw_date < rules.archive_start:
            errors.append(
                f"{prefix}: date precedes archive start on {rules.archive_start}; "
                "only draws on or after this date are supported."
            )
        if rules.draw_weekdays and not rules.is_draw_day(draw_date):
            errors.append(f"{prefix}: date is not a scheduled draw day.")

        try:
            numbers = [int(row[f"n{j}"]) for j in range(1, rules.num_count + 1)]
        except ValueError as exc:
            errors.append(f"{prefix}: could not parse numbers — {exc}")
            continue
        if len(set(numbers)) != rules.num_count:
            errors.append(f"{prefix}: duplicate numbers {numbers}")
        out_of_range = [n for n in numbers
                        if not rules.number_min <= n <= rules.number_max]
        if out_of_range:
            errors.append(
                f"{prefix}: numbers out of range "
                f"{rules.number_min}-{rules.number_max}: {out_of_range}"
            )
        if numbers != sorted(numbers):
            errors.append(f"{prefix}: main numbers are not sorted ascending: {numbers}")

        extras: list[int] = []
        extra_max = rules.extra_limit(draw_date)
        for field_name in rules.extra_fields:
            raw_extra = row[field_name].strip()
            if not raw_extra:
                if draw_date >= rules.extras_required_from:
                    errors.append(f"{prefix}: missing required {field_name}.")
                continue
            if draw_date < rules.extras_required_from:
                errors.append(f"{prefix}: {field_name} did not exist before "
                              f"{rules.extras_required_from}.")
            try:
                extra = int(raw_extra)
            except ValueError as exc:
                errors.append(f"{prefix}: could not parse {field_name} — {exc}")
                continue
            extras.append(extra)
            if not rules.extra_min <= extra <= extra_max:
                errors.append(f"{prefix}: {field_name} {extra} out of range "
                              f"{rules.extra_min}-{extra_max}")
            if rules.extras_separate_from_main and extra in numbers:
                errors.append(f"{prefix}: {field_name} {extra} duplicates a main number.")
        if len(set(extras)) != len(extras):
            errors.append(f"{prefix}: duplicate extra numbers {extras}")
        if extras != sorted(extras):
            errors.append(f"{prefix}: extra numbers are not sorted ascending: {extras}")

    if rules.draw_weekdays and dates:
        recorded_dates = set(dates)
        cursor, last_date = min(dates), max(dates)
        missing = []
        while cursor < last_date:
            if rules.is_draw_day(cursor) and cursor not in recorded_dates:
                missing.append(cursor.isoformat())
            cursor += timedelta(days=1)
        if missing:
            preview = ", ".join(missing[:10])
            suffix = f", … ({len(missing)} total)" if len(missing) > 10 else ""
            errors.append(f"Missing scheduled draw(s) within archive: {preview}{suffix}.")

    if not skip_stale and dates:
        last_date = max(dates)
        days_since = (today - last_date).days
        if days_since > rules.max_stale_days:
            errors.append(
                f"Data is stale: last draw was {last_date} "
                f"({days_since} day(s) ago, threshold is {rules.max_stale_days} days). "
                "A draw may have been missed."
            )
    return errors, len(records)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument("--country", choices=("at", "de", "eu"), type=str.lower,
                          help="Legacy selector: eu checks EuroMillions only.")
    selector.add_argument("--game", choices=("at", "de", "eu", "euromillions", "eurojackpot"),
                          type=str.lower, help="Check one game; omit to check all four.")
    parser.add_argument("--skip-stale", action="store_true",
                        help="Skip freshness only, for offline/historical validation.")
    args = parser.parse_args(argv)
    selected = args.game or args.country
    if selected == "eu":
        selected = "euromillions"
    games = [game for game in GAMES if selected is None or game.game_id == selected]

    if args.skip_stale:
        print("Note: stale-data check explicitly skipped.")
    all_passed = True
    for rules in games:
        print(f"Checking {rules.label} ({rules.csv_path})...")
        errors, count = check_csv(rules, skip_stale=args.skip_stale)
        if errors:
            all_passed = False
            print(f"  FAILED — {len(errors)} issue(s):")
            for error in errors:
                print(f"    - {error}")
        else:
            print(f"  OK — {count} draw(s), all checks passed.")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
