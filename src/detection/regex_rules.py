# Purpose: High-precision regex and checksum detectors for Indian IDs, phones, emails, PINs, and dates.
"""High-precision regex and checksum detectors for structured and free-text fields."""

from __future__ import annotations

from dataclasses import dataclass
import re

from src.contracts import SpanRole
from src.detection.normalization import (
    IndexedText,
    normalize_date,
    normalize_phone,
    normalize_with_offset_map,
)

# Official Verhoeff dihedral D5, permutation, and inverse tables for Aadhaar validation.
_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def verhoeff_check(digits: str) -> bool:
    """Validate an Aadhaar-length digit string using the Verhoeff checksum."""
    if len(digits) != 12 or not digits.isdigit() or digits[0] in ("0", "1"):
        return False
    c = 0
    for idx, ch in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[idx % 8][int(ch)]]
    return c == 0


@dataclass(frozen=True, slots=True)
class RegexCandidate:
    """Intermediate detection candidate mapped back to original UTF-8 coordinates."""

    start: int
    end: int
    category: str
    role: SpanRole
    confidence: float
    detector_source: str
    canonical_attr_key: str | None = None
    canonical_attr_val: str | None = None
    extra_attr_key: str | None = None
    extra_attr_val: str | None = None


_ABHA_PHR_RE = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9._-]{1,40}@(?:abdm|ndhm|sbx)\b", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_WEB_URL_RE = re.compile(r"(?i)\bhttps?://[^\s<>\]\[(){}\"']+")

_ABHA_LABELED_RE = re.compile(
    r"\b(?:ABHA(?:\s*(?:ID|No|Number))?|Ayushman\s*ID|Health\s*ID|आभा(?:\s*(?:आईडी|नंबर))?)"
    r"\s*[:=#-]?\s*(\d{2}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}|\d{14})\b",
    re.IGNORECASE,
)
_ABHA_FORMAT_RE = re.compile(r"(?<!\d)(\d{2}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4})(?!\d)")

_AADHAAR_LABELED_RE = re.compile(
    r"\b(?:Aadhaar|Aadhar|UIDAI|UID|आधार(?:\s*(?:नंबर|संख्या))?)"
    r"\s*[:=#-]?\s*((?:\d{4}[\s-]?\d{4}[\s-]?\d{4})|(?:[Xx*]{4}[\s-]?[Xx*]{4}[\s-]?\d{4}))\b",
    re.IGNORECASE,
)
_AADHAAR_UNLABELED_RE = re.compile(r"(?<!\d)([2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4})(?!\d)")
_OCR_AADHAAR_LABELED_RE = re.compile(
    r"(?i)\b(?:Aadhaar|Aadhar|UIDAI|UID)\s*[:=#-]?\s*((?:[0-9OIl]{4}[\s-]?){2}[0-9OIl]{4})\b"
)
_OCR_LABELED_PHONE_RE = re.compile(
    r"(?i)\b(?:Phone|Mobile|Mob|Contact|Tel)\s*[:=#-]?\s*([6-9][0-9OIl](?:[\s.-]?[0-9OIl]){8})\b"
)
_OCR_LABELED_PIN_RE = re.compile(
    r"(?i)\b(?:PIN(?:\s*Code)?|Pincode|Postal\s*Code)\s*[:=#-]?\s*([1-8][0-9OIl]{5})\b"
)
_OCR_LABELED_DATE_RE = re.compile(
    r"(?i)\b(?:DOB|D\.O\.B\.?|Date\s+of\s+Birth)\s*[:=#-]?\s*([0-9OIl]{1,2}[/-][0-9OIl]{1,2}[/-][0-9OIl]{4})\b"
)

_PAN_LABELED_RE = re.compile(
    r"\b(?:PAN(?:\s*(?:No|Number|Card|ID))?|पैन)\s*[:=#-]?\s*([A-Z]{5}\d{4}[A-Z])\b",
    re.IGNORECASE,
)
_PAN_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z])(?![A-Z0-9])")

# Require at least one digit inside local ID values so plain words never match.
_LOCAL_ID_RE = re.compile(
    r"\b(?P<kind>UHID|MRN|MR\.?\s*No|CR\.?\s*No|EMR\s*ID|"
    r"IPD(?:\s*(?:No|ID))?|OPD(?:\s*(?:No|ID))?|IP\s*No|OP\s*No|Case\s*No|"
    r"Hosp(?:ital)?\s*ID|Reg(?:n|istration)?\.?\s*(?:No|ID)|Patient\s*ID|Pt\s*ID|यूएचआईडी|एमआरएन)"
    r"\.?\s*[:=#-]?\s*(?P<val>(?=[A-Z0-9/_-]*\d)[A-Z0-9][A-Z0-9/_-]{2,22})\b",
    re.IGNORECASE,
)
_EXTRA_LOCAL_ID_RE = re.compile(
    r"(?i)\b(?:PPO|Belt\s*No\.?|Report\s*No\.?|Reg(?:istration)?\.?|Ref(?:erence)?\s*(?:No|ID|Ref)|"
    r"Auth(?:orization)?\s*(?:No|ID|Ref)|Staff\s*ID)\s*[:=#-]?\s*"
    r"(?P<val>(?=[A-Z0-9/_-]*\d)[A-Z0-9][A-Z0-9/_-]{2,30})\b"
)
_STAFF_BADGE_RE = re.compile(r"(?i)\[STAFF\]\s*(?P<val>/[A-Z0-9_-]+(?:/[A-Z0-9_-]+)+)")

_INSURANCE_RE = re.compile(
    r"\b(?:Insurance(?:\s*(?:ID|No|Number|Card))?|Policy(?:\s*(?:No|Number|ID))?|TPA\s*ID|"
    r"Ayushman\s*Card|बीमा(?:\s*(?:नंबर|संख्या|आईडी))?)\.?\s*[:=#-]?\s*"
    r"(?P<val>(?=[A-Z0-9/_-]*\d)[A-Z0-9][A-Z0-9/_-]{3,24})\b",
    re.IGNORECASE,
)

_PHONE_CANDIDATE_RE = re.compile(
    r"(?<!\d)(?:\+\d{1,3}[\s.-]?(?:\(\s*0\s*\)[\s.-]?)?)?"
    r"(?:\(\s*0?\d{2,5}\s*\)[\s.-]?)?"
    r"(?:0091[\s.-]?|91[\s.-]?|0)?"
    r"[1-9]\d(?:[\s.-]?\d){7,12}(?!\d)"
)

_PIN_LABELED_RE = re.compile(
    r"\b(?:PIN(?:\s*Code)?|Pincode|Postal\s*Code|पिन(?:\s*कोड)?)\s*[:=#-]?\s*([1-8]\d{2}\s?\d{3})\b",
    re.IGNORECASE,
)
_PIN_CONTEXT_RE = re.compile(
    r"(?:,\s*|\s-\s)([1-8]\d{5})(?!\d)(?!\s*(?:mg|mcg|ml|g|iu)\b)",
    re.IGNORECASE,
)

# Numeric dates (supports both 1-digit and 2-digit day/month for DD/MM/YYYY and DD-MM-YYYY).
_NUMERIC_DATE_RE = re.compile(
    r"(?<!\d)(?:"
    r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))?|"
    r"\d{4}/\d{2}/\d{2}|"
    r"\d{1,2}/\d{1,2}/\d{4}|"
    r"\d{1,2}-\d{1,2}-\d{4}"
    r")(?!\d)"
)
_TEXT_DATE_RE = re.compile(
    r"\b\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|"
    r"जनवरी|फरवरी|मार्च|अप्रैल|मई|जून|जुलाई|अगस्त|सितंबर|सितम्बर|अक्टूबर|अक्तूबर|नवंबर|नवम्बर|दिसंबर|दिसम्बर)"
    r",?\s+\d{4}\b",
    re.IGNORECASE,
)

_DOB_CUE_RE = re.compile(r"(?:dob|d\.o\.b\.?|date\s+of\s+birth|birth\s*date|born|जन्म\s*तिथि)\s*[:=\-]?\s*$", re.IGNORECASE)
_DOA_CUE_RE = re.compile(r"(?:doa|admitted(?:\s+on)?|admission(?:\s+date)?|भर्ती(?:\s+तिथि)?)\s*[:=\-]?\s*$", re.IGNORECASE)
_DOD_CUE_RE = re.compile(r"(?:dod|discharged(?:\s+on)?|discharge(?:\s+date)?|छुट्टी(?:\s+तिथि)?)\s*[:=\-]?\s*$", re.IGNORECASE)
_VISIT_CUE_RE = re.compile(r"(?:visit(?:\s+date)?|encounter(?:\s+date)?|date|दिनांक|तारीख)\s*[:=\-]?\s*$", re.IGNORECASE)

_CLINICAL_UNIT_FOLLOW_RE = re.compile(r"^\s*(?:mg|mcg|ug|g|gm|ml|iu|units?|%|mmhg|bpm)\b", re.IGNORECASE)
_M3_NUMERIC_SHIFT_RE = re.compile(
    r"^\s*(?:\d{4}-\d{2}-\d{2}(?:T.*)?|\d{2}/\d{2}/\d{4}|\d{2}-\d{2}-\d{4}|\d{4}/\d{2}/\d{2})\s*$"
)


def _infer_date_category(left_window: str) -> str:
    if _DOB_CUE_RE.search(left_window):
        return "DOB"
    if _DOA_CUE_RE.search(left_window):
        return "ADMISSION_DATE"
    if _DOD_CUE_RE.search(left_window):
        return "DISCHARGE_DATE"
    if _VISIT_CUE_RE.search(left_window):
        return "VISIT_DATE"
    return "DATE"


def detect_regex_candidates(
    raw_text: str,
    *,
    issuer: str = "UNKNOWN_HOSPITAL",
    indexed: IndexedText | None = None,
) -> list[RegexCandidate]:
    """Run high-precision identifier, phone, PIN, and date detectors on `raw_text`."""
    if not raw_text or not raw_text.strip():
        return []

    idx_text = indexed or normalize_with_offset_map(raw_text)
    norm = idx_text.normalized
    candidates: list[RegexCandidate] = []
    occupied_strong_ids: list[tuple[int, int]] = []

    # 1. ABHA PHR addresses and Emails
    for m in _ABHA_PHR_RE.finditer(norm):
        s, e = idx_text.to_original_span(m.start(), m.end())
        candidates.append(
            RegexCandidate(
                start=s,
                end=e,
                category="ABHA",
                role=SpanRole.DIRECT_PII,
                confidence=0.97,
                detector_source="regex_abha_phr",
                canonical_attr_key="ids",
                canonical_attr_val=f"ABHA|{m.group(0).lower()}",
            )
        )
        occupied_strong_ids.append((m.start(), m.end()))

    for m in _EMAIL_RE.finditer(norm):
        if any(m.start() < oe and os < m.end() for os, oe in occupied_strong_ids):
            continue
        s, e = idx_text.to_original_span(m.start(), m.end())
        candidates.append(
            RegexCandidate(
                start=s,
                end=e,
                category="EMAIL",
                role=SpanRole.DIRECT_PII,
                confidence=0.99,
                detector_source="regex_email",
            )
        )

    for m in _WEB_URL_RE.finditer(norm):
        s, e = idx_text.to_original_span(m.start(), m.end())
        candidates.append(
            RegexCandidate(
                start=s, end=e, category="URL", role=SpanRole.DIRECT_PII,
                confidence=0.97, detector_source="regex_url",
            )
        )

    # 2. ABHA 14-digit health IDs
    for pattern, conf in ((_ABHA_LABELED_RE, 0.99), (_ABHA_FORMAT_RE, 0.95)):
        for m in pattern.finditer(norm):
            val_start, val_end = m.span(1)
            digits = re.sub(r"\D", "", m.group(1))
            if len(digits) != 14:
                continue
            s, e = idx_text.to_original_span(val_start, val_end)
            candidates.append(
                RegexCandidate(
                    start=s,
                    end=e,
                    category="ABHA",
                    role=SpanRole.DIRECT_PII,
                    confidence=conf,
                    detector_source="regex_abha",
                    canonical_attr_key="ids",
                    canonical_attr_val=f"ABHA|{digits}",
                )
            )
            occupied_strong_ids.append((val_start, val_end))

    # 3. Aadhaar (labeled or Verhoeff-validated 12-digit)
    for m in _AADHAAR_LABELED_RE.finditer(norm):
        val_start, val_end = m.span(1)
        if any(val_start < oe and os < val_end for os, oe in occupied_strong_ids):
            continue
        digits = re.sub(r"\D", "", m.group(1))
        s, e = idx_text.to_original_span(val_start, val_end)
        is_full = len(digits) == 12
        candidates.append(
            RegexCandidate(
                start=s,
                end=e,
                category="AADHAAR",
                role=SpanRole.DIRECT_PII,
                confidence=0.98,
                detector_source="regex_aadhaar_labeled",
                canonical_attr_key="ids" if is_full else None,
                canonical_attr_val=f"AADHAAR|{digits}" if is_full else None,
            )
        )
        occupied_strong_ids.append((val_start, val_end))

    for m in _OCR_AADHAAR_LABELED_RE.finditer(norm):
        val_start, val_end = m.span(1)
        if any(val_start < oe and os < val_end for os, oe in occupied_strong_ids):
            continue
        s, e = idx_text.to_original_span(val_start, val_end)
        candidates.append(RegexCandidate(
            start=s, end=e, category="AADHAAR", role=SpanRole.DIRECT_PII,
            confidence=0.93, detector_source="regex_aadhaar_ocr",
        ))
        occupied_strong_ids.append((val_start, val_end))

    for m in _OCR_LABELED_DATE_RE.finditer(norm):
        s, e = idx_text.to_original_span(*m.span(1))
        candidates.append(RegexCandidate(
            start=s, end=e, category="DOB", role=SpanRole.QUASI_IDENTIFIER,
            confidence=0.92, detector_source="regex_dob_ocr",
        ))

    for m in _AADHAAR_UNLABELED_RE.finditer(norm):
        val_start, val_end = m.span(1)
        if any(val_start < oe and os < val_end for os, oe in occupied_strong_ids):
            continue
        digits = re.sub(r"\D", "", m.group(1))
        if verhoeff_check(digits):
            s, e = idx_text.to_original_span(val_start, val_end)
            candidates.append(
                RegexCandidate(
                    start=s,
                    end=e,
                    category="AADHAAR",
                    role=SpanRole.DIRECT_PII,
                    confidence=0.92,
                    detector_source="regex_aadhaar_verhoeff",
                    canonical_attr_key="ids",
                    canonical_attr_val=f"AADHAAR|{digits}",
                )
            )
            occupied_strong_ids.append((val_start, val_end))

    # 4. PAN (labeled accepts any 5L-4D-1L synthetic PAN; unlabeled enforces official 4th-char type)
    for m in _PAN_LABELED_RE.finditer(norm):
        val_start, val_end = m.span(1)
        if any(val_start < oe and os < val_end for os, oe in occupied_strong_ids):
            continue
        pan_val = m.group(1).upper()
        s, e = idx_text.to_original_span(val_start, val_end)
        candidates.append(
            RegexCandidate(
                start=s,
                end=e,
                category="PAN",
                role=SpanRole.DIRECT_PII,
                confidence=0.98,
                detector_source="regex_pan_labeled",
                canonical_attr_key="ids",
                canonical_attr_val=f"PAN|{pan_val}",
            )
        )
        occupied_strong_ids.append((val_start, val_end))

    for m in _PAN_RE.finditer(norm):
        val_start, val_end = m.span(1)
        if any(val_start < oe and os < val_end for os, oe in occupied_strong_ids):
            continue
        s, e = idx_text.to_original_span(val_start, val_end)
        candidates.append(
            RegexCandidate(
                start=s,
                end=e,
                category="PAN",
                role=SpanRole.DIRECT_PII,
                confidence=0.96,
                detector_source="regex_pan",
                canonical_attr_key="ids",
                canonical_attr_val=f"PAN|{m.group(1).upper()}",
            )
        )
        occupied_strong_ids.append((val_start, val_end))

    # 5. Local hospital IDs (UHID / MRN / IPD / OPD / Case / Patient ID) & Insurance IDs
    safe_issuer = re.sub(r"[^A-Z0-9_]", "_", issuer.upper()).strip("_") or "UNKNOWN_HOSPITAL"
    for m in _LOCAL_ID_RE.finditer(norm):
        kind_raw = m.group("kind").upper()
        val_raw = m.group("val").strip()
        val_start, val_end = m.span("val")
        if any(val_start < oe and os < val_end for os, oe in occupied_strong_ids):
            continue
        if "MRN" in kind_raw or "MR" in kind_raw or "एमआरएन" in kind_raw:
            cat, id_type = "MRN", "MRN"
        elif "UHID" in kind_raw or "यूएचआईडी" in kind_raw:
            cat, id_type = "UHID", "UHID"
        elif "PATIENT" in kind_raw or "PT" in kind_raw:
            cat, id_type = "PATIENT_IDENTIFIER", "UHID"
        else:
            cat, id_type = "UHID", "UHID"
        s, e = idx_text.to_original_span(val_start, val_end)
        candidates.append(
            RegexCandidate(
                start=s,
                end=e,
                category=cat,
                role=SpanRole.DIRECT_PII,
                confidence=0.95,
                detector_source="regex_local_id",
                canonical_attr_key="ids",
                canonical_attr_val=f"{id_type}|{safe_issuer}|{val_raw.upper()}",
            )
        )
        occupied_strong_ids.append((val_start, val_end))

    for pattern, category, source in (
        (_EXTRA_LOCAL_ID_RE, "CASE_NO", "regex_contextual_id"),
        (_STAFF_BADGE_RE, "STAFF_IDENTIFIER", "regex_staff_badge"),
    ):
        for m in pattern.finditer(norm):
            val_start, val_end = m.span("val")
            if any(val_start < oe and os < val_end for os, oe in occupied_strong_ids):
                continue
            s, e = idx_text.to_original_span(val_start, val_end)
            candidates.append(RegexCandidate(
                start=s, end=e, category=category, role=SpanRole.DIRECT_PII,
                confidence=0.94, detector_source=source,
            ))
            occupied_strong_ids.append((val_start, val_end))

    for m in _INSURANCE_RE.finditer(norm):
        val_start, val_end = m.span("val")
        if any(val_start < oe and os < val_end for os, oe in occupied_strong_ids):
            continue
        s, e = idx_text.to_original_span(val_start, val_end)
        candidates.append(
            RegexCandidate(
                start=s,
                end=e,
                category="INSURANCE_ID",
                role=SpanRole.DIRECT_PII,
                confidence=0.94,
                detector_source="regex_insurance",
                canonical_attr_key="ids",
                canonical_attr_val=f"INSURANCE|{safe_issuer}|{m.group('val').upper()}",
            )
        )
        occupied_strong_ids.append((val_start, val_end))

    # 6. Phone numbers (validated strictly by normalize_phone)
    for m in _PHONE_CANDIDATE_RE.finditer(norm):
        if any(m.start() < oe and os < m.end() for os, oe in occupied_strong_ids):
            continue
        if _CLINICAL_UNIT_FOLLOW_RE.match(norm[m.end() : m.end() + 12]):
            continue
        parsed_phone = normalize_phone(m.group(0))
        if parsed_phone is None:
            continue
        s, e = idx_text.to_original_span(m.start(), m.end())
        candidates.append(
            RegexCandidate(
                start=s,
                end=e,
                category="PHONE",
                role=SpanRole.DIRECT_PII,
                confidence=0.96,
                detector_source="regex_phone",
                canonical_attr_key="phones",
                canonical_attr_val=parsed_phone.e164,
            )
        )
        occupied_strong_ids.append((m.start(), m.end()))

    for m in _OCR_LABELED_PHONE_RE.finditer(norm):
        val_start, val_end = m.span(1)
        if any(val_start < oe and os < val_end for os, oe in occupied_strong_ids):
            continue
        s, e = idx_text.to_original_span(val_start, val_end)
        candidates.append(RegexCandidate(
            start=s, end=e, category="PHONE", role=SpanRole.DIRECT_PII,
            confidence=0.91, detector_source="regex_phone_ocr",
        ))
        occupied_strong_ids.append((val_start, val_end))

    for m in _OCR_LABELED_PIN_RE.finditer(norm):
        val_start, val_end = m.span(1)
        if any(val_start < oe and os < val_end for os, oe in occupied_strong_ids):
            continue
        s, e = idx_text.to_original_span(val_start, val_end)
        candidates.append(RegexCandidate(
            start=s, end=e, category="PIN_CODE", role=SpanRole.QUASI_IDENTIFIER,
            confidence=0.90, detector_source="regex_pin_ocr",
        ))

    # 7. PIN Codes
    for pattern, conf in ((_PIN_LABELED_RE, 0.96), (_PIN_CONTEXT_RE, 0.85)):
        for m in pattern.finditer(norm):
            val_start, val_end = m.span(1)
            if any(val_start < oe and os < val_end for os, oe in occupied_strong_ids):
                continue
            digits = re.sub(r"\D", "", m.group(1))
            if len(digits) != 6:
                continue
            s, e = idx_text.to_original_span(val_start, val_end)
            candidates.append(
                RegexCandidate(
                    start=s,
                    end=e,
                    category="PIN_CODE",
                    role=SpanRole.QUASI_IDENTIFIER,
                    confidence=conf,
                    detector_source="regex_pin",
                    canonical_attr_key="geo_keys",
                    canonical_attr_val=f"PIN_{digits[:3]}",
                )
            )

    # 8. Dates (Numeric & Text)
    for m in _NUMERIC_DATE_RE.finditer(norm):
        if any(m.start() < oe and os < m.end() for os, oe in occupied_strong_ids):
            continue
        parsed_date = normalize_date(m.group(0))
        if parsed_date is None or not parsed_date.iso_date:
            continue
        left_window = norm[max(0, m.start() - 32) : m.start()]
        date_cat = _infer_date_category(left_window)
        s, e = idx_text.to_original_span(m.start(), m.end())
        span_cat = date_cat if _M3_NUMERIC_SHIFT_RE.match(idx_text.original[s:e]) else "TEXT_DATE"
        attr_key = "dobs" if date_cat == "DOB" else None
        extra_key = "birth_years" if date_cat == "DOB" else "visit_years"
        candidates.append(
            RegexCandidate(
                start=s,
                end=e,
                category=span_cat,
                role=SpanRole.QUASI_IDENTIFIER,
                confidence=0.94 if date_cat != "DATE" else 0.88,
                detector_source="regex_numeric_date",
                canonical_attr_key=attr_key,
                canonical_attr_val=parsed_date.iso_date if attr_key else None,
                extra_attr_key=extra_key,
                extra_attr_val=parsed_date.year,
            )
        )

    for m in _TEXT_DATE_RE.finditer(norm):
        parsed_date = normalize_date(m.group(0))
        if parsed_date is None or not parsed_date.iso_date:
            continue
        left_window = norm[max(0, m.start() - 32) : m.start()]
        date_cat = _infer_date_category(left_window)
        s, e = idx_text.to_original_span(m.start(), m.end())
        attr_key = "dobs" if date_cat == "DOB" else None
        extra_key = "birth_years" if date_cat == "DOB" else "visit_years"
        candidates.append(
            RegexCandidate(
                start=s,
                end=e,
                category="TEXT_DATE",
                role=SpanRole.QUASI_IDENTIFIER,
                confidence=0.90,
                detector_source="regex_text_date",
                canonical_attr_key=attr_key,
                canonical_attr_val=parsed_date.iso_date if attr_key else None,
                extra_attr_key=extra_key,
                extra_attr_val=parsed_date.year,
            )
        )

    return candidates
