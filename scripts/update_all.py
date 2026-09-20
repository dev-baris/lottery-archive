#!/usr/bin/env python3
"""Update all four lottery archives, optionally committing each game separately.

Usage:
  python scripts/update_all.py                 # update CSVs without requiring Git
  python scripts/update_all.py --init          # import configured archive history
  python scripts/update_all.py --init --commit # also create one commit per game

Every collector is attempted even if another fails. Any failed fetch, write, or
requested commit makes the process exit unsuccessfully, so automation can retry.
AT and DE Lotto archives begin in 2000; EuroMillions begins in 2004 and
Eurojackpot in 2012.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import fetch_eurojackpot as fetch_ej
import fetch_euromillions as fetch_eu
import fetch_lotto_at_6aus45 as fetch_at
import fetch_lotto_de_6aus49 as fetch_de
from git_utils import git_commit


def update_country(
    label: str,
    game: str,
    csv_file: str,
    new_draws: list,
    *,
    commit: bool = False,
) -> int:
    """Report written draws and optionally commit only this game's results file."""
    if not new_draws:
        print(f"{label}: No new draws.")
        # A previous run may have written this CSV before its commit failed.
        if commit and Path(csv_file).is_file():
            if git_commit(csv_file, f"Update {label} {game} results"):
                print(f"{label}: Committed pending results file changes.")
        return 0

    dates = ", ".join(d.date for d in new_draws)
    if commit:
        message = f"Add {label} {game} results: {dates}"
        if git_commit(csv_file, message):
            print(f"{label}: Committed {len(new_draws)} new draw(s) — {dates}")
        else:
            print(f"{label}: File unchanged after write — nothing to commit.")
    else:
        print(f"{label}: Wrote {len(new_draws)} new draw(s) — {dates}")
    return len(new_draws)


def main(argv: list[str] | None = None) -> int:
    """Return the draw count on success, or -1 if any collector fails."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init", action="store_true", help="Import history from each game's archive start")
    parser.add_argument(
        "--commit", action="store_true", help="Create a Git commit for each updated game"
    )
    args = parser.parse_args(argv)
    total = 0
    failed: list[str] = []
    collectors = (
        ("AT", "Lotto 6 aus 45", fetch_at),
        ("DE", "Lotto 6 aus 49", fetch_de),
        ("EU", "EuroMillions", fetch_eu),
        ("EJ", "Eurojackpot", fetch_ej),
    )
    for label, game, collector in collectors:
        try:
            new_draws = collector.fetch_new_draws(init=args.init)
            if new_draws:
                collector.write_draws(new_draws)
            total += update_country(
                label,
                game,
                str(collector.RESULTS_CSV),
                new_draws,
                commit=args.commit,
            )
        except Exception as exc:
            failed.append(label)
            print(f"{label} update failed: {exc}", file=sys.stderr)

    if failed:
        print(f"Update incomplete; failed game(s): {', '.join(failed)}.", file=sys.stderr)
        return -1
    if total == 0:
        print("No new draws in any archive.")
    return total


if __name__ == "__main__":
    sys.exit(0 if main() >= 0 else 1)
