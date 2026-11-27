# Purpose: Applies PrivacyDecisions safely to string fields using reverse-offset splicing and clinical-span protection.
"""Safe text transformation and clinical-integrity guard for serialization."""

from __future__ import annotations

from typing import Sequence
import re

from src.contracts import DetectionSpan, PatientRecord, PrivacyDecision, SpanRole, TransformType


def _record_applied(record, field_path, decision, before, after):
    if before == after:
        return
    events = record.field_metadata.setdefault('applied_events', {})
    key = f'{field_path}:{decision.start}:{decision.end}:{decision.transform_type}'
    events[key] = str(decision.transform_type)


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
        "[PATIENT]", "[RELATIVE]", "[PERSON]", "[STAFF]", "[PHONE]", "[AADHAAR]", "[PAN]",
        "[ABHA]", "[DL]", "[EMAIL]", "[IP]", "[USERNAME]", "[CASE_NO]",
        "[ID_MARK]", "[ADDRESS]", "[IDENTITY_HINT]",
        "[DATE]", "[PPO]", "[SENIOR_CARD]", "[AUTH_REF]", "[URL]",
        "[HOUSE_NO]", "[CCTV_ID]", "[EVENT]",
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
            _record_applied(record, field_path, candidate, raw_value, candidate.replacement_value or '')
            return candidate.replacement_value if candidate.replacement_value is not None else "", blocked
        elif candidate.replacement_value is not None:
            _record_applied(record, field_path, candidate, raw_value, candidate.replacement_value)
            return candidate.replacement_value, blocked

    # Apply span-level decisions in reverse offset order so earlier indices stay valid.
    span_decisions = [
        d for d in decisions if d.start is not None and d.end is not None
    ]
    if not span_decisions:
        return raw_value, blocked

    def priority(decision: PrivacyDecision) -> int:
        value = decision.replacement_value or ""
        if value.startswith("PSN-"):
            return 5
        if value in {"[PATIENT]", "[RELATIVE]", "[PERSON]", "[STAFF]"}:
            return 4
        if decision.transform_type == TransformType.DATE_SHIFT:
            return 3
        return 2

    chosen: list[PrivacyDecision] = []
    for decision in sorted(
        span_decisions,
        key=lambda d: (d.start or 0, -((d.end or 0) - (d.start or 0)), -priority(d)),
    ):
        assert decision.start is not None and decision.end is not None
        if any(decision.start < (old.end or 0) and (old.start or 0) < decision.end for old in chosen):
            continue
        chosen.append(decision)
    span_decisions = sorted(chosen, key=lambda d: (d.start or 0, d.end or 0), reverse=True)
    result = raw_value
    last_applied_start = len(raw_value) + 1

    for dec in span_decisions:
        assert dec.start is not None and dec.end is not None
        if dec.start < 0 or dec.end > len(raw_value) or dec.start > dec.end:
            continue
        if dec.replacement_value in {'[PATIENT]', '[RELATIVE]', '[PERSON]', '[STAFF]'} or (dec.replacement_value or '').startswith('PSN-'):
            doctors = re.finditer(r'(?:\bDr\.?|डॉ\.?|ڈاکٹر)[ \t]+[^\W\d_][\w.\u0600-\u06ff\u0900-\u097f]*(?:[ \t]+[^\W\d_][\w.\u0600-\u06ff\u0900-\u097f]*){0,3}', raw_value)
            if any(dec.start < doctor.end() and doctor.start() < dec.end for doctor in doctors):
                blocked += 1
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
        _record_applied(record, field_path, dec, raw_value[dec.start:dec.end], replacement)
        last_applied_start = dec.start

    return result, blocked
