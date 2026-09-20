"""Validated archive I/O shared by the lottery importers.

An unreadable archive must never turn into a shorter, apparently successful
update. Read every row strictly, and replace the original only after the full
merged file has been validated and written successfully.
"""

import csv
import os
import sys
import tempfile
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path
from typing import TypeVar

DrawT = TypeVar("DrawT", bound=tuple)


def validate_iso_date(
    raw: str, *, first_date: date | None = None,
) -> tuple[bool, str]:
    """Require an actual calendar date in the canonical YYYY-MM-DD format."""
    try:
        parsed = date.fromisoformat(raw)
    except (ValueError, TypeError):
        return False, f"invalid ISO date: {raw!r}"
    if parsed.isoformat() != raw:
        return False, f"noncanonical ISO date: {raw!r}"
    if first_date is not None and parsed < first_date:
        return False, f"date {raw} precedes the first draw ({first_date})"
    return True, ""


def report_parse_issue(message: str, *, strict: bool) -> None:
    """Fail an import on a malformed draw; permit diagnostic parsing on demand."""
    if strict:
        raise ValueError(message)
    print(f"  WARNING: {message}", file=sys.stderr)


def validate_source_draws(
    draws: Iterable[DrawT],
    source: str,
    *,
    year: int | None = None,
    allow_empty: bool = False,
    today: date | None = None,
) -> list[DrawT]:
    """Reject empty, misrouted, future-dated, or contradictory source data."""
    today = today or date.today()
    unique: dict[str, DrawT] = {}
    for draw in draws:
        valid, reason = validate_iso_date(draw[0])
        if not valid:
            raise ValueError(f"{source}: {reason}")
        draw_date = date.fromisoformat(draw[0])
        if year is not None and draw_date.year != year:
            raise ValueError(
                f"{source}: requested {year}, received draw dated {draw[0]}"
            )
        if draw_date > today:
            raise ValueError(f"{source}: future draw dated {draw[0]}")
        previous = unique.get(draw[0])
        if previous is not None and previous != draw:
            raise ValueError(f"{source}: conflicting draws for {draw[0]}")
        unique[draw[0]] = draw
    if not unique and not allow_empty:
        raise ValueError(f"{source}: no valid draws found; source format may have changed")
    return sorted(unique.values(), key=lambda draw: draw[0])


def read_draws(
    csv_path: Path,
    draw_type: type[DrawT],
    validate: Callable[[DrawT], tuple[bool, str]],
    *,
    nullable_fields: frozenset[str] = frozenset(),
) -> list[DrawT]:
    """Load every stored row or raise, with a precise location for corruption."""
    if not csv_path.exists():
        return []
    fields = list(draw_type._fields)
    draws: list[DrawT] = []
    seen: set[str] = set()
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle, strict=True)
        try:
            header = next(reader, None)
            if header != fields:
                raise ValueError(f"{csv_path}: expected CSV header {','.join(fields)}")
            for row in reader:
                if len(row) != len(fields):
                    raise ValueError(
                        f"{csv_path}:{reader.line_num}: expected {len(fields)} fields, "
                        f"received {len(row)}"
                    )
                try:
                    values = [row[0]] + [
                        None if field in nullable_fields and not value.strip() else int(value)
                        for field, value in zip(fields[1:], row[1:])
                    ]
                    draw = draw_type(*values)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"{csv_path}:{reader.line_num}: invalid draw values: {exc}"
                    ) from exc
                valid, reason = validate(draw)
                if not valid:
                    raise ValueError(f"{csv_path}:{reader.line_num}: {reason}")
                if draw[0] in seen:
                    raise ValueError(
                        f"{csv_path}:{reader.line_num}: duplicate date {draw[0]}"
                    )
                seen.add(draw[0])
                draws.append(draw)
        except (csv.Error, UnicodeError) as exc:
            raise ValueError(f"{csv_path}:{reader.line_num}: invalid CSV: {exc}") from exc
    return draws


def write_draws_atomic(
    csv_path: Path,
    draws: Iterable[DrawT],
    draw_type: type[DrawT],
    validate: Callable[[DrawT], tuple[bool, str]],
    *,
    nullable_fields: frozenset[str] = frozenset(),
) -> None:
    """Merge explicit draw updates, then atomically replace the sorted archive."""
    existing = read_draws(csv_path, draw_type, validate, nullable_fields=nullable_fields)
    incoming: dict[str, DrawT] = {}
    for draw in draws:
        valid, reason = validate(draw)
        if not valid:
            raise ValueError(f"refusing to write invalid draw {draw[0]}: {reason}")
        if draw[0] in incoming and incoming[draw[0]] != draw:
            raise ValueError(f"conflicting incoming draws for {draw[0]}")
        incoming[draw[0]] = draw
    merged = {draw[0]: draw for draw in existing}
    merged.update(incoming)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", newline="", encoding="utf-8", dir=csv_path.parent,
            prefix=f".{csv_path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(draw_type._fields)
            writer.writerows(sorted(merged.values(), key=lambda draw: draw[0]))
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.chmod(csv_path.stat().st_mode & 0o777 if csv_path.exists() else 0o644)
        os.replace(temporary_path, csv_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
