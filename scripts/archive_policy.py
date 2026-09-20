"""Shared archive scope, independent of when each lottery was introduced."""

from datetime import date

from archive_utils import validate_iso_date

LOTTO_FIRST_YEAR = 2000
LOTTO_FIRST_DATE = date(LOTTO_FIRST_YEAR, 1, 1)


def validate_lotto_archive_date(raw: str) -> tuple[bool, str]:
    """Require a canonical date within the retained AT/DE Lotto history."""
    valid, reason = validate_iso_date(raw)
    if not valid:
        return valid, reason
    if raw < LOTTO_FIRST_DATE.isoformat():
        return False, f"date {raw} precedes archive start ({LOTTO_FIRST_DATE})"
    return True, ""
