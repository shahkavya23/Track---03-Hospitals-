# Purpose: ClinicalIntegrityGuard enforcing CLINICAL_PROTECTED precedence and extracting protected attributes.
"""Clinical integrity guard protecting medical concepts from PII redaction."""

from __future__ import annotations

import re
from typing import Sequence

from src.contracts import DetectionSpan, FieldNode, PatientRecord, SpanRole
from src.detection.normalization import normalize_with_offset_map

from .conditions import detect_condition_and_procedure_spans
from .medications import ClinicalMatch, detect_medication_spans
from .vitals_labs import detect_vital_and_lab_spans

# Direct identifiers that a broad clinical rule must NEVER conceal.
HARD_DIRECT_PII_CATEGORIES = frozenset({
    "PHONE",
    "EMAIL",
    "AADHAAR",
    "ABHA",
    "PAN",
    "UHID",
    "MRN",
    "INSURANCE_ID",
    "PATIENT_IDENTIFIER",
})

# Structured fields whose entire clean value represents a clinical concept (unless containing hard PII).
STRUCTURED_CLINICAL_HEADERS = frozenset({
    "diagnosis",
    "diagnoses",
    "primary_diagnosis",
    "secondary_diagnosis",
    "condition",
    "chief_complaint",
    "complaint",
    "symptoms",
    "medication",
    "medications",
    "drug",
    "drugs",
    "dosage",
    "dose",
    "frequency",
    "vitals",
    "vital_signs",
    "lab_result",
    "lab_value",
    "procedure",
    "procedures",
    "treatment",
    "prescription",
    "rx",
})

_NULL_LIKE = frozenset({"", "n/a", "na", "none", "null", "-", "--", "---"})


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def _merge_clinical_matches(matches: Sequence[ClinicalMatch]) -> list[ClinicalMatch]:
    """Merge overlapping or duplicate clinical spans, preferring longer/higher-confidence spans."""
    if not matches:
        return []
    ordered = sorted(
        matches,
        key=lambda m: (m.start, -(m.end - m.start), -m.confidence, m.category),
    )
    merged: list[ClinicalMatch] = []
    for item in ordered:
        if not merged:
            merged.append(item)
            continue
        prev = merged[-1]
        if item.start <= prev.end:
            # Extend or subsume overlapping clinical spans of compatible type.
            if item.end > prev.end:
                merged[-1] = ClinicalMatch(
                    start=prev.start,
                    end=item.end,
                    category=prev.category if (prev.end - prev.start) >= (item.end - item.start) else item.category,
                    confidence=max(prev.confidence, item.confidence),
                )
        else:
            merged.append(item)
    return merged


_CLINICAL_HEADER_TOKENS = frozenset({
    "diagnosis", "diagnoses", "dx", "condition", "conditions",
    "complaint", "complaints", "symptom", "symptoms",
    "medication", "medications", "med", "meds", "drug", "drugs",
    "dosage", "dose", "frequency", "vital", "vitals", "lab", "labs",
    "procedure", "procedures", "treatment", "prescription", "rx",
    "impression", "assessment", "findings",
})


def _is_structured_clinical_field(node: FieldNode) -> bool:
    if not node.is_structured_key:
        return False
    norm_key = node.header_key.strip().lower().replace(" ", "_")
    if norm_key in STRUCTURED_CLINICAL_HEADERS:
        return True
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", node.header_key.strip())
    tokens = {t.lower() for t in re.split(r"[\s_\-./:]+", camel_split) if t}
    if tokens & _CLINICAL_HEADER_TOKENS:
        return True
    # Check FHIR clinical coding display/text paths without protecting Patient/Practitioner names.
    fp = node.field_path.lower()
    if any(seg in fp for seg in ("/condition/", "/medication", "/observation/", "/procedure/")):
        if fp.endswith(("/display", "/text", "/code", "/unit", "/valuequantity/value")):
            return True
    return False


class ClinicalIntegrityGuard:
    """Implements Member 2 `ClinicalGuard` protocol with strict precedence rules."""

    def extract_clinical_spans(self, record: PatientRecord) -> list[DetectionSpan]:
        """Scan every FieldNode in `record` for clinical concepts to protect."""
        spans: list[DetectionSpan] = []
        for node in record.fields:
            raw = node.raw_value
            if not raw or raw.strip().lower() in _NULL_LIKE:
                continue

            indexed = normalize_with_offset_map(raw)
            matches: list[ClinicalMatch] = []
            matches.extend(detect_medication_spans(raw, indexed))
            matches.extend(detect_vital_and_lab_spans(raw, indexed))
            matches.extend(detect_condition_and_procedure_spans(raw, indexed))

            # If it's a dedicated structured clinical field and doesn't look empty, protect the whole text.
            if _is_structured_clinical_field(node):
                stripped = raw.strip()
                if stripped:
                    lead = len(raw) - len(raw.lstrip())
                    trail = len(raw.rstrip())
                    matches.append(
                        ClinicalMatch(
                            start=lead,
                            end=trail,
                            category="CLINICAL",
                            confidence=0.98,
                        )
                    )

            for match in _merge_clinical_matches(matches):
                spans.append(
                    DetectionSpan(
                        record_ref=record.record_ref,
                        field_path=node.field_path,
                        start=match.start,
                        end=match.end,
                        category=match.category,
                        role=SpanRole.CLINICAL_PROTECTED,
                        confidence=match.confidence,
                        detector_source="clinical_guard",
                    )
                )
        return spans

    def protect_clinical(
        self,
        record: PatientRecord,
        spans: Sequence[DetectionSpan],
    ) -> tuple[list[DetectionSpan], list[str]]:
        """Enforce `CLINICAL_PROTECTED` precedence while never concealing hard PII."""
        incoming_clinical = [s for s in spans if s.role == SpanRole.CLINICAL_PROTECTED]
        detected_clinical = self.extract_clinical_spans(record)
        all_clinical_raw = incoming_clinical + detected_clinical

        # Hard PII spans always win against overlapping broad clinical guesses (anti-concealment).
        hard_pii_spans = [
            s
            for s in spans
            if s.role == SpanRole.DIRECT_PII and s.category.upper() in HARD_DIRECT_PII_CATEGORIES
        ]

        safe_clinical_spans: list[DetectionSpan] = []
        for cspan in all_clinical_raw:
            overlapping_hard = [
                h
                for h in hard_pii_spans
                if h.field_path == cspan.field_path and _overlaps(cspan.start, cspan.end, h.start, h.end)
            ]
            if not overlapping_hard:
                safe_clinical_spans.append(cspan)
                continue
            # Carve out segments not overlapping hard PII if a structured clinical field held embedded PII.
            cursor = cspan.start
            for h in sorted(overlapping_hard, key=lambda x: (x.start, x.end)):
                if h.start > cursor:
                    sub_raw = _field_slice(record, cspan.field_path, cursor, h.start).strip()
                    if sub_raw:
                        safe_clinical_spans.append(
                            DetectionSpan(
                                record_ref=cspan.record_ref,
                                field_path=cspan.field_path,
                                start=cursor,
                                end=h.start,
                                category=cspan.category,
                                role=SpanRole.CLINICAL_PROTECTED,
                                confidence=cspan.confidence,
                                detector_source=cspan.detector_source,
                            )
                        )
                cursor = max(cursor, h.end)
            if cursor < cspan.end:
                sub_raw = _field_slice(record, cspan.field_path, cursor, cspan.end).strip()
                if sub_raw:
                    safe_clinical_spans.append(
                        DetectionSpan(
                            record_ref=cspan.record_ref,
                            field_path=cspan.field_path,
                            start=cursor,
                            end=cspan.end,
                            category=cspan.category,
                            role=SpanRole.CLINICAL_PROTECTED,
                            confidence=cspan.confidence,
                            detector_source=cspan.detector_source,
                        )
                    )

        # Deduplicate merged clinical spans per field_path.
        deduped_clinical = _dedupe_clinical_spans(safe_clinical_spans)

        # Drop any non-clinical span that overlaps a confirmed CLINICAL_PROTECTED span
        # (unless it is a hard-validated direct identifier).
        final_non_clinical: list[DetectionSpan] = []
        for span in spans:
            if span.role == SpanRole.CLINICAL_PROTECTED:
                continue
            if span.is_header_detection:
                final_non_clinical.append(span)
                continue
            if span.category.upper() in HARD_DIRECT_PII_CATEGORIES:
                final_non_clinical.append(span)
                continue
            overlaps_clinical = any(
                c.field_path == span.field_path and _overlaps(span.start, span.end, c.start, c.end)
                for c in deduped_clinical
            )
            if not overlaps_clinical:
                final_non_clinical.append(span)

        final_spans = sorted(
            final_non_clinical + deduped_clinical,
            key=lambda s: (s.field_path, s.start, s.end, s.role),
        )

        # Extract exact substrings for M1 post-serialization integrity check.
        fields_by_path = {node.field_path: node for node in record.fields}
        clinical_attrs: list[str] = []
        seen_attrs: set[str] = set()
        diagnoses_for_profile: list[str] = []

        for cspan in deduped_clinical:
            node = fields_by_path.get(cspan.field_path)
            if node is None or cspan.end > len(node.raw_value):
                continue
            exact_val = node.raw_value[cspan.start : cspan.end]
            if exact_val.strip() and exact_val not in seen_attrs:
                seen_attrs.add(exact_val)
                clinical_attrs.append(exact_val)
            if cspan.category.upper() in {"DIAGNOSIS", "CLINICAL"} and exact_val.strip():
                diagnoses_for_profile.append(exact_val.strip().lower())

        if diagnoses_for_profile:
            existing_dx = set(record.extracted_patient_attributes.get("diagnoses", []))
            for dx in diagnoses_for_profile:
                if dx not in existing_dx:
                    record.extracted_patient_attributes.setdefault("diagnoses", []).append(dx)
                    existing_dx.add(dx)

        return final_spans, clinical_attrs


def _field_slice(record: PatientRecord, field_path: str, start: int, end: int) -> str:
    for node in record.fields:
        if node.field_path == field_path:
            return node.raw_value[start:end]
    return ""


def _dedupe_clinical_spans(spans: Sequence[DetectionSpan]) -> list[DetectionSpan]:
    by_field: dict[str, list[DetectionSpan]] = {}
    for s in spans:
        by_field.setdefault(s.field_path, []).append(s)

    result: list[DetectionSpan] = []
    for field_path in sorted(by_field):
        ordered = sorted(
            by_field[field_path],
            key=lambda s: (s.start, -(s.end - s.start), -s.confidence),
        )
        merged: list[DetectionSpan] = []
        for s in ordered:
            if not merged:
                merged.append(s)
                continue
            prev = merged[-1]
            if s.start <= prev.end:
                if s.end > prev.end:
                    merged[-1] = DetectionSpan(
                        record_ref=prev.record_ref,
                        field_path=prev.field_path,
                        start=prev.start,
                        end=s.end,
                        category=prev.category if (prev.end - prev.start) >= (s.end - s.start) else s.category,
                        role=SpanRole.CLINICAL_PROTECTED,
                        confidence=max(prev.confidence, s.confidence),
                        detector_source=prev.detector_source,
                    )
            else:
                merged.append(s)
        result.extend(merged)
    return result
