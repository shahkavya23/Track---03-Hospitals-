# Purpose: Applies PrivacyDecisions safely to string fields using reverse-offset splicing and clinical-span protection.
"""Safe text transformation and clinical-integrity guard for serialization."""

from __future__ import annotations

from typing import Sequence

from src.contracts import DetectionSpan, PatientRecord, PrivacyDecision, SpanRole, TransformType


def _clinical_spans_for_field(
    record: PatientRecord, field_path: str
) -> list[DetectionSpan]:
    return [
        span
        for span in record.detections
        if span.role == SpanRole.CLINICAL_PROTECTED and span.field_path == field_path
    ]


def _overlaps_clinical(
    clinical_spans: Sequence[DetectionSpan],
    start: int | None,
    end: int | None,
) -> bool:
    if not clinical_spans:
        return False
    if start is None or end is None:
        return True
    return any(start < span.end and end > span.start for span in clinical_spans)


def _hard_privacy_replacement(value: str | None) -> bool:
    """Typed identifiers take precedence even inside a clinically protected field."""
    return value in {
        "[PATIENT]", "[RELATIVE]", "[STAFF]", "[PHONE]", "[AADHAAR]", "[PAN]",
        "[ABHA]", "[DL]", "[EMAIL]", "[IP]", "[USERNAME]", "[CASE_NO]",
        "[ID_MARK]", "[ADDRESS]", "[IDENTITY_HINT]",
        "[DATE]",
    }


def apply_decisions_to_field(
    raw_value: str,
    record: PatientRecord,
    field_path: str,
) -> tuple[str, int]:
    """Apply all PrivacyDecisions for `field_path`, preserving CLINICAL_PROTECTED spans.

    Returns `(transformed_text, blocked_clinical_mutations)`.
    """
    decisions = [
        dec
        for dec in record.privacy_decisions
        if dec.field_path == field_path
        and dec.transform_type != TransformType.PRESERVE_CLINICAL
    ]
    if not decisions:
        return raw_value, 0

    clinical_spans = _clinical_spans_for_field(record, field_path)
    blocked = 0

    # Check whole-field decisions first (start is None or end is None).
    whole_field = [d for d in decisions if d.start is None or d.end is None]
    if whole_field:
        candidate = whole_field[-1]
        if _overlaps_clinical(clinical_spans, None, None):
            blocked += len(whole_field)
        elif candidate.transform_type == TransformType.SUPPRESS:
            return candidate.replacement_value if candidate.replacement_value is not None else "", blocked
        elif candidate.replacement_value is not None:
            return candidate.replacement_value, blocked

    # Apply span-level decisions in reverse offset order so earlier indices stay valid.
    span_decisions = [
        d for d in decisions if d.start is not None and d.end is not None
    ]
    if not span_decisions:
        return raw_value, blocked

    # Prefer larger enclosing spans over nested sub-spans so that full redactions (e.g. [ADDRESS])
    # are not skipped due to reverse-offset collision with smaller inner spans.
    filtered_spans = []
    for d in sorted(span_decisions, key=lambda x: ((x.end or 0) - (x.start or 0)), reverse=True):
        if not any(other.start <= d.start and other.end >= d.end for other in filtered_spans):
            filtered_spans.append(d)
    span_decisions = filtered_spans

    span_decisions.sort(key=lambda d: (d.start or 0, d.end or 0), reverse=True)
    result = raw_value
    last_applied_start = len(raw_value) + 1

    for dec in span_decisions:
        assert dec.start is not None and dec.end is not None
        if dec.start < 0 or dec.end > len(raw_value) or dec.start > dec.end:
            continue
        if (
            _overlaps_clinical(clinical_spans, dec.start, dec.end)
            and dec.transform_type != TransformType.DATE_SHIFT
            and dec.replacement_value != ""
            and not _hard_privacy_replacement(dec.replacement_value)
        ):
            blocked += 1
            continue
        # Guard against overlapping/duplicate span edits corrupting offsets.
        if dec.end > last_applied_start:
            continue
        replacement = (
            "" if dec.transform_type == TransformType.SUPPRESS and dec.replacement_value is None
            else (dec.replacement_value if dec.replacement_value is not None else "[REDACTED]")
        )
        result = result[: dec.start] + replacement + result[dec.end :]
        last_applied_start = dec.start

    return result, blocked
