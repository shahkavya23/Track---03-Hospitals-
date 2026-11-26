"""Multilingual PII detection layer — owned by Member 2."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .normalization import (
    IndexedText,
    NormalizedDate,
    NormalizedName,
    NormalizedPhone,
    normalize_date,
    normalize_person_name,
    normalize_phone,
    normalize_with_offset_map,
    phonetic_token_key,
    transliterate_devanagari,
    transliterate_with_map,
)
from .regex_rules import verhoeff_check

if TYPE_CHECKING:
    from .detector import MultilingualPIIDetector

__all__ = [
    "IndexedText",
    "MultilingualPIIDetector",
    "NormalizedDate",
    "NormalizedName",
    "NormalizedPhone",
    "normalize_date",
    "normalize_person_name",
    "normalize_phone",
    "normalize_with_offset_map",
    "phonetic_token_key",
    "transliterate_devanagari",
    "transliterate_with_map",
    "verhoeff_check",
]


def __getattr__(name: str) -> Any:
    # Lazy export prevents circular imports when src.clinical imports src.detection.normalization.
    if name == "MultilingualPIIDetector":
        from .detector import MultilingualPIIDetector

        return MultilingualPIIDetector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
