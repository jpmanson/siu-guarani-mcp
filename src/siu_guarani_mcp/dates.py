from __future__ import annotations

from datetime import date, datetime


def parse_date_input(value: str | date | datetime | None, *, field_name: str = "fecha") -> str | None:
    """Normalize a date input to SIU format dd/mm/YYYY.

    Accepts:
    - None
    - date/datetime
    - dd/mm/yyyy or d/m/yyyy
    - yyyy-mm-dd
    - yyyy-mm-ddTHH:MM[:SS][Z|+hh:mm]
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().strftime("%d/%m/%Y")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")

    raw = str(value).strip()
    if not raw:
        return None

    # ISO date or datetime: 2026-07-21, 2026-07-21T18:00:00Z, 2026-07-21T18:00:00-03:00
    iso_candidate = raw.replace("Z", "+00:00")
    try:
        if "T" in iso_candidate:
            return datetime.fromisoformat(iso_candidate).date().strftime("%d/%m/%Y")
        if len(iso_candidate) >= 10 and iso_candidate[4] == "-" and iso_candidate[7] == "-":
            return date.fromisoformat(iso_candidate[:10]).strftime("%d/%m/%Y")
    except ValueError:
        pass

    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date().strftime("%d/%m/%Y")
        except ValueError:
            continue

    raise ValueError(
        f"{field_name} inválida: {value!r}. Usá dd/mm/aaaa o ISO yyyy-mm-dd[/T...]."
    )
