# Purpose: Deterministic Indian & E.164 phone number normalization with PIN/date safeguards.
"""Phone number normalization and false-positive digit guards."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .unicode_map import normalize_with_offset_map

try:
    import phonenumbers  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - pure-Python fallback is always available
    phonenumbers = None

_PIN_SIX_DIGIT_RE = re.compile(r"^\s*[1-8]\d{2}\s?\d{3}\s*$")
_ISO_DATE_RE = re.compile(r"^\s*\d{4}[-/]\d{2}[-/]\d{2}\s*$")
_ALLOWED_PHONE_CHARS_RE = re.compile(r"^[\d\s+\-().]+$")


@dataclass(frozen=True, slots=True)
class NormalizedPhone:
    """Canonical phone representation for linkage and detection verification."""

    e164: str
    country_code: str
    national_number: str
    is_mobile: bool
    provenance: tuple[str, ...]


def normalize_phone(raw: str, default_country: str = "IN") -> NormalizedPhone | None:
    """Parse and canonicalize a phone string to E.164, rejecting PINs/dates/short numbers."""
    if not raw or not raw.strip():
        return None

    normalized_text = normalize_with_offset_map(raw).normalized.strip()
    if not normalized_text or not _ALLOWED_PHONE_CHARS_RE.match(normalized_text):
        return None

    # Guard against 6-digit Indian PIN codes (e.g. "411 045") and ISO dates.
    if _PIN_SIX_DIGIT_RE.match(normalized_text) or _ISO_DATE_RE.match(normalized_text):
        return None

    provenance: list[str] = []
    # Strip formatting like "(0)" often used in "+91 (0) 98765-43210".
    compact = re.sub(r"\(\s*0\s*\)", "", normalized_text)
    if compact != normalized_text:
        provenance.append("STRIP_TRUNK_PAREN_ZERO")

    has_plus = compact.startswith("+")
    digits = re.sub(r"\D", "", compact)

    if len(digits) < 10 or len(digits) > 15:
        return None

    if phonenumbers is not None:
        try:
            parsed = phonenumbers.parse(compact, None if has_plus else default_country)
            if phonenumbers.is_valid_number(parsed):
                e164 = phonenumbers.format_number(
                    parsed, phonenumbers.PhoneNumberFormat.E164
                )
                cc = str(parsed.country_code)
                nn = str(parsed.national_number)
                is_mobile = cc == "91" and len(nn) == 10 and nn[0] in "6789"
                provenance.append("PHONENUMBERS_LIB")
                return NormalizedPhone(
                    e164=e164,
                    country_code=cc,
                    national_number=nn,
                    is_mobile=is_mobile,
                    provenance=tuple(sorted(set(provenance))),
                )
        except Exception:
            pass

    # Pure-Python deterministic normalization (handles offline runtime without optional libs).
    if default_country == "IN":
        national: str | None = None
        if has_plus:
            if digits.startswith("91") and len(digits) == 12:
                national = digits[2:]
                provenance.append("IN_PLUS91")
            elif 10 <= len(digits) <= 15:
                # Non-IN international E.164
                provenance.append("INTL_E164")
                return NormalizedPhone(
                    e164=f"+{digits}",
                    country_code=digits[:-10] or "1",
                    national_number=digits[-10:],
                    is_mobile=False,
                    provenance=tuple(sorted(set(provenance))),
                )
        else:
            if digits.startswith("0091") and len(digits) == 14:
                national = digits[4:]
                provenance.append("IN_0091")
            elif digits.startswith("91") and len(digits) == 12:
                national = digits[2:]
                provenance.append("IN_91")
            elif digits.startswith("0") and len(digits) == 11:
                national = digits[1:]
                provenance.append("IN_TRUNK_ZERO")
            elif len(digits) == 10:
                national = digits
                provenance.append("IN_10_DIGIT")

        if national is not None and len(national) == 10:
            is_mobile = national[0] in "6789"
            is_landline = national[0] in "12345" and (
                has_plus or digits.startswith(("0", "91", "0091")) or "(" in normalized_text
            )
            if is_mobile or is_landline:
                return NormalizedPhone(
                    e164=f"+91{national}",
                    country_code="91",
                    national_number=national,
                    is_mobile=is_mobile,
                    provenance=tuple(sorted(set(provenance))),
                )

    return None
