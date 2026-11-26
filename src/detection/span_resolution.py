# Purpose: Deterministic span conflict resolution across multiple overlapping PII/role detectors.
"""Overlap and role conflict resolution for DetectionSpans."""

from __future__ import annotations

from typing import Sequence

from src.contracts import DetectionSpan, SpanRole

# Priority tier (higher number wins when two non-clinical spans overlap).
_CATEGORY_PRIORITY: dict[str, int] = {
    "CLINICAL": 100,
    "MEDICATION": 100,
    "DOSAGE": 100,
    "FREQUENCY": 100,
    "VITAL_SIGN": 100,
    "LAB_VALUE": 100,
    "DIAGNOSIS": 100,
    "PROCEDURE": 100,
    "CLINICIAN_NAME": 90,
    "FACILITY_NAME": 88,
    "ABHA": 85,
    "AADHAAR": 84,
    "PAN": 83,
    "EMAIL": 82,
    "PHONE": 81,
    "UHID": 80,
    "MRN": 80,
    "INSURANCE_ID": 79,
    "PATIENT_IDENTIFIER": 78,
    "RELATIVE_NAME": 75,
    "PATIENT_NAME": 72,
    "PERSON_NAME": 65,
    "OTHER_PERSON_NAME": 60,
    "ADDRESS": 55,
    "DOB": 50,
    "ADMISSION_DATE": 50,
    "DISCHARGE_DATE": 50,
    "VISIT_DATE": 48,
    "DATE": 45,
    "AGE": 44,
    "PIN_CODE": 42,
    "VILLAGE": 40,
    "LOCATION": 40,
    "TEXT_DATE": 35,
}


def _span_rank(span: DetectionSpan) -> tuple[int, int, int, float, int]:
    """Deterministic ranking key for conflict resolution."""
    if span.role == SpanRole.CLINICAL_PROTECTED:
        tier = 100
    elif span.role == SpanRole.STAFF_OR_FACILITY:
        tier = _CATEGORY_PRIORITY.get(span.category.upper(), 85)
    else:
        tier = _CATEGORY_PRIORITY.get(span.category.upper(), 50)
    is_primary = 0 if span.detector_source.startswith("entity_propagation_") else 1
    structured_bonus = 1 if span.detector_source.startswith("structured_") else 0
    length = span.end - span.start
    return (tier, is_primary, structured_bonus, span.confidence, length)


def resolve_span_conflicts(spans: Sequence[DetectionSpan]) -> list[DetectionSpan]:
    """Resolve overlapping detections deterministically per `(field_path, is_header_detection)`."""
    buckets: dict[tuple[str, bool], list[DetectionSpan]] = {}
    for span in spans:
        buckets.setdefault((span.field_path, span.is_header_detection), []).append(span)

    resolved: list[DetectionSpan] = []
    for key in sorted(buckets):
        candidates = sorted(
            buckets[key],
            key=lambda s: (_span_rank(s), -s.start, s.end),
            reverse=True,
        )
        accepted: list[DetectionSpan] = []
        for cand in candidates:
            overlaps = any(
                cand.start < acc.end and acc.start < cand.end
                for acc in accepted
            )
            if not overlaps:
                accepted.append(cand)
        accepted.sort(key=lambda s: (s.start, s.end, s.category))
        resolved.extend(accepted)

    return resolved
