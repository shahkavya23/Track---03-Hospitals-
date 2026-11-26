# Purpose: Structural unit-anchored vital-sign and laboratory-value detection.
"""Vital-sign and laboratory-value clinical span detectors."""

from __future__ import annotations

import re

from src.detection.normalization import IndexedText, normalize_with_offset_map

from .medications import ClinicalMatch

# Comprehensive clinical measurement units (covers unseen lab tests without hardcoding analyte names).
_CLINICAL_UNITS = (
    r"(?:mg/dL|g/dL|gm/dL|gm%|mmol/L|mEq/L|U/L|IU/L|mIU/L|µIU/mL|uIU/mL|"
    r"ng/mL|pg/mL|mcg/dL|ug/dL|mcg/L|fL|pg|/cumm|/mm3|/µL|/uL|cells/cumm|"
    r"lakhs?|%|mm/hr|mmHg|mm\s*Hg|mL/min|L/min|kPa|IU/mL|U/mL|bpm|/min|per\s*min)"
)

# Vital signs anchored by physiological label + numeric format/ratio.
_BP_RE = re.compile(
    r"\b(?:BP|B\.P\.|Blood\s+Pressure|रक्तचाप)\s*[:=\-]?\s*\d{2,3}\s*/\s*\d{2,3}(?:\s*mm\s*Hg)?\b",
    re.IGNORECASE,
)
_VITAL_RATE_RE = re.compile(
    r"\b(?:PR|HR|Pulse|Heart\s+Rate|RR|Resp(?:iratory)?\s*Rate|नाड़ी)\s*[:=\-]?\s*\d{2,3}(?:\s*(?:bpm|/min|per\s*min))?\b",
    re.IGNORECASE,
)
_SPO2_RE = re.compile(
    r"\b(?:SpO2|SPO2|O2\s*Sat(?:uration)?)\s*[:=\-]?\s*\d{2,3}\s*%(?:\s*on\s*(?:RA|room\s*air|\d+\s*L\s*O2))?",
    re.IGNORECASE,
)
_TEMP_RE = re.compile(
    r"\b(?:Temp(?:erature)?|तापमान)\s*[:=\-]?\s*\d{2,3}(?:\.\d+)?\s*(?:°\s*)?[FC]\b",
    re.IGNORECASE,
)
_ANTHRO_RE = re.compile(
    r"\b(?:Wt|Weight|वजन)\s*[:=\-]?\s*\d{1,3}(?:\.\d+)?\s*(?:kg|g|lbs?)\b|"
    r"\b(?:Ht|Height|कद)\s*[:=\-]?\s*\d{2,3}(?:\.\d+)?\s*(?:cm|m|ft|in)\b|"
    r"\bBMI\s*[:=\-]?\s*\d{1,2}(?:\.\d+)?(?:\s*kg/m2)?\b|"
    r"\bGCS\s*[:=\-]?\s*\d{1,2}/15\b",
    re.IGNORECASE,
)

# General multi-word analyte + numeric value + explicit clinical unit (catches any unseen lab test).
_UNIT_ANCHORED_LAB_RE = re.compile(
    rf"\b(?!(?:age|id|uhid|mrn|abha|pin|dob|doa|dod|phone|mobile|patient|name)\b)"
    rf"(?:(?:Sr\.?|Serum|Blood|Plasma|Urine|Total|Direct|Indirect|Fasting|Random|Postprandial)\s+)?"
    rf"[A-Za-z][A-Za-z0-9+/-]{{1,22}}(?:\s+[A-Za-z0-9+/-]{{1,18}})?"
    rf"\s*[:=\-]?\s*\d+(?:,\d{{3}})*(?:\.\d+)?\s*{_CLINICAL_UNITS}",
    re.IGNORECASE,
)

# Common unitless clinical score/ratio labs (e.g. "INR 1.1", "eGFR 68", "HbA1c 7.4", "pH 7.38").
_UNITLESS_LAB_RE = re.compile(
    r"\b(?:HbA1c|INR|eGFR|APTT|PT|pH|PCO2|PO2|HCO3)\s*[:=\-]?\s*\d+(?:\.\d+)?%?\b",
    re.IGNORECASE,
)


def detect_vital_and_lab_spans(
    raw_text: str,
    indexed: IndexedText | None = None,
) -> list[ClinicalMatch]:
    """Detect vital signs and laboratory values with exact original bounds."""
    if not raw_text or not raw_text.strip():
        return []

    idx_text = indexed or normalize_with_offset_map(raw_text)
    norm = idx_text.normalized
    matches: list[ClinicalMatch] = []

    patterns: tuple[tuple[re.Pattern[str], str, float], ...] = (
        (_BP_RE, "VITAL_SIGN", 0.98),
        (_VITAL_RATE_RE, "VITAL_SIGN", 0.95),
        (_SPO2_RE, "VITAL_SIGN", 0.97),
        (_TEMP_RE, "VITAL_SIGN", 0.95),
        (_ANTHRO_RE, "VITAL_SIGN", 0.94),
        (_UNIT_ANCHORED_LAB_RE, "LAB_VALUE", 0.95),
        (_UNITLESS_LAB_RE, "LAB_VALUE", 0.93),
    )

    for pattern, category, confidence in patterns:
        for m in pattern.finditer(norm):
            s, e = idx_text.to_original_span(m.start(), m.end())
            if s < e:
                matches.append(ClinicalMatch(start=s, end=e, category=category, confidence=confidence))

    return matches
