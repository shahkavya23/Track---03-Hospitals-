# Purpose: Multilingual Indian, ISO, and Hindi-month date normalization with clinical schedule guards.
"""Date normalization for English, Hindi, and Indian hospital date formats."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re

from .unicode_map import normalize_with_offset_map

_CLINICAL_SCHEDULE_RE = re.compile(r"^\s*[0-2]-[0-2]-[0-2](?:-[0-2])?\s*$")
_BP_RATIO_RE = re.compile(r"^\s*\d{2,3}/\d{2,3}\s*$")

_HINDI_MONTHS: dict[str, str] = {
    "जनवरी": "January",
    "फरवरी": "February",
    "मार्च": "March",
    "अप्रैल": "April",
    "मई": "May",
    "जून": "June",
    "जुलाई": "July",
    "अगस्त": "August",
    "सितंबर": "September",
    "सितम्बर": "September",
    "अक्टूबर": "October",
    "अक्तूबर": "October",
    "नवंबर": "November",
    "नवम्बर": "November",
    "दिसंबर": "December",
    "दिसम्बर": "December",
}

_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%b %d %Y",
    "%B %d %Y",
)


@dataclass(frozen=True, slots=True)
class NormalizedDate:
    """Canonical date representation compatible with Member 3 linkage and date shifting."""

    iso_date: str
    year: str
    precision: str
    provenance: tuple[str, ...]


def normalize_date(raw: str, *, min_year: int = 1900, max_year: int = 2100) -> NormalizedDate | None:
    """Parse English, Hindi, or Indian numeric date strings into `YYYY-MM-DD`.

    Explicitly rejects clinical dosage schedules (`1-0-1`) and BP ratios (`150/90`).
    """
    if not raw or not raw.strip():
        return None

    indexed = normalize_with_offset_map(raw)
    cleaned = indexed.normalized.strip()
    if not cleaned:
        return None

    if _CLINICAL_SCHEDULE_RE.match(cleaned) or _BP_RATIO_RE.match(cleaned):
        return None

    provenance = list(indexed.provenance)

    for hi_month, en_month in _HINDI_MONTHS.items():
        if hi_month in cleaned:
            cleaned = cleaned.replace(hi_month, en_month)
            provenance.append("HINDI_MONTH")

    # Handle ISO datetime strings (e.g. "1985-04-12T08:30:00Z")
    if "T" in cleaned:
        iso_candidate = cleaned[:-1] + "+00:00" if cleaned.endswith("Z") else cleaned
        try:
            dt = datetime.fromisoformat(iso_candidate)
            if min_year <= dt.year <= max_year:
                provenance.append("ISO_DATETIME")
                return NormalizedDate(
                    iso_date=dt.date().isoformat(),
                    year=f"{dt.year:04d}",
                    precision="day",
                    provenance=tuple(sorted(set(provenance))),
                )
        except ValueError:
            pass

    for fmt in _DATE_FORMATS:
        try:
            parsed: date = datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
        if min_year <= parsed.year <= max_year:
            provenance.append("EXACT_DATE")
            return NormalizedDate(
                iso_date=parsed.isoformat(),
                year=f"{parsed.year:04d}",
                precision="day",
                provenance=tuple(sorted(set(provenance))),
            )

    # Support pure 4-digit birth/visit year if explicitly bounded.
    if re.fullmatch(r"(?:19|20)\d{2}", cleaned):
        yr = int(cleaned)
        if min_year <= yr <= max_year:
            provenance.append("YEAR_ONLY")
            return NormalizedDate(
                iso_date="",
                year=cleaned,
                precision="year",
                provenance=tuple(sorted(set(provenance))),
            )

    return None
