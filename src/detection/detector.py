# Purpose: MultilingualPIIDetector implementing the Member 2 PIIDetector Protocol.
"""Integrated Member 2 multilingual PII detector."""

from __future__ import annotations

from src.clinical.guard import ClinicalIntegrityGuard, HARD_DIRECT_PII_CATEGORIES
from src.contracts import DetectionSpan, PatientRecord
from src.detection.normalization import normalize_with_offset_map

from .context_rules import detect_context_candidates
from .entities import propagate_known_names_in_record
from .regex_rules import detect_regex_candidates
from .span_resolution import resolve_span_conflicts
from .structured_fields import (
    analyze_structured_field,
    build_fhir_resource_map,
    infer_record_facility_issuer,
)


def _append_attr(record: PatientRecord, key: str | None, value: str | None) -> None:
    if not key or not value:
        return
    cleaned = value.strip()
    if not cleaned:
        return
    bucket = record.extracted_patient_attributes.setdefault(key, [])
    if cleaned not in bucket:
        bucket.append(cleaned)


class MultilingualPIIDetector:
    """Protocol-compatible Member 2 detector across EN, Hindi (Devanagari), and Hinglish."""

    def __init__(self, clinical_guard: ClinicalIntegrityGuard | None = None) -> None:
        self._clinical_guard = clinical_guard or ClinicalIntegrityGuard()

    def analyze_record(self, record: PatientRecord) -> list[DetectionSpan]:
        """Detect multilingual PII, QIs, and staff entities on `record`."""
        record.extracted_patient_attributes.clear()

        issuer = infer_record_facility_issuer(record)
        fhir_resource_map = build_fhir_resource_map(record)
        clinical_spans = self._clinical_guard.extract_clinical_spans(record)
        clinical_by_field: dict[str, list[DetectionSpan]] = {}
        for cs in clinical_spans:
            clinical_by_field.setdefault(cs.field_path, []).append(cs)

        raw_candidates: list[DetectionSpan] = []
        # Hold candidate attributes keyed by span identity until conflict resolution picks winners.
        pending_attrs: dict[tuple[str, int, int, str, str], list[tuple[str, str]]] = {}

        def queue_attr(span: DetectionSpan, key: str | None, val: str | None) -> None:
            if not key or not val:
                return
            sig = (span.field_path, span.start, span.end, span.category, span.detector_source)
            pending_attrs.setdefault(sig, []).append((key, val))

        for node in record.fields:
            # 1. Structured column/JSON/FHIR analysis (plus header/key PII checks)
            structured_spans = analyze_structured_field(
                record, node, issuer, fhir_resource_map=fhir_resource_map
            )
            raw_candidates.extend(structured_spans)

            # Skip free-text regex/context passes on non-textual system keys.
            if node.is_structured_key and node.header_key.lower() in {
                "resourcetype", "system", "code", "status", "use", "reference", "fullurl"
            }:
                continue

            raw = node.raw_value
            if not raw or not raw.strip():
                continue

            indexed = normalize_with_offset_map(raw)
            field_clinical = clinical_by_field.get(node.field_path, [])

            # 2. High-precision regex/checksum pass (phones, emails, Aadhaar, ABHA, PAN, UHID, PIN, dates)
            for rc in detect_regex_candidates(raw, issuer=issuer, indexed=indexed):
                if rc.category not in HARD_DIRECT_PII_CATEGORIES and any(
                    rc.start < cs.end and cs.start < rc.end for cs in field_clinical
                ):
                    continue
                span = DetectionSpan(
                    record_ref=record.record_ref,
                    field_path=node.field_path,
                    start=rc.start,
                    end=rc.end,
                    category=rc.category,
                    role=rc.role,
                    confidence=rc.confidence,
                    detector_source=rc.detector_source,
                )
                raw_candidates.append(span)
                queue_attr(span, rc.canonical_attr_key, rc.canonical_attr_val)
                queue_attr(span, rc.extra_attr_key, rc.extra_attr_val)

            # 3. Multilingual context rules (Dr., S/o, W/o, D/o, C/O, labeled patient, age, address)
            for cc in detect_context_candidates(raw, indexed=indexed):
                if cc.category not in HARD_DIRECT_PII_CATEGORIES and any(
                    cc.start < cs.end and cs.start < cc.end for cs in field_clinical
                ):
                    continue
                span = DetectionSpan(
                    record_ref=record.record_ref,
                    field_path=node.field_path,
                    start=cc.start,
                    end=cc.end,
                    category=cc.category,
                    role=cc.role,
                    confidence=cc.confidence,
                    detector_source=cc.detector_source,
                )
                raw_candidates.append(span)
                queue_attr(span, cc.attr_key, cc.attr_val)
                queue_attr(span, cc.extra_attr_key, cc.extra_attr_val)

        # 4. Resolve overlaps among non-clinical PII/QI/Staff candidates.
        initial_resolved = resolve_span_conflicts(raw_candidates)

        # 5. Propagate high-confidence patient/relative names across narrative fields.
        propagated = propagate_known_names_in_record(record, initial_resolved)
        filtered_propagated: list[DetectionSpan] = []
        for ps in propagated:
            field_clinical = clinical_by_field.get(ps.field_path, [])
            if any(ps.start < cs.end and cs.start < ps.end for cs in field_clinical):
                continue
            filtered_propagated.append(ps)

        pii_resolved = resolve_span_conflicts(initial_resolved + filtered_propagated)

        # 6. Apply ClinicalIntegrityGuard precedence (carves clinical fields around hard PII).
        final_spans, _ = self._clinical_guard.protect_clinical(record, pii_resolved)

        # Commit pending attributes ONLY for spans that survived conflict resolution & clinical guard.
        for sp in final_spans:
            sig = (sp.field_path, sp.start, sp.end, sp.category, sp.detector_source)
            for attr_key, attr_val in pending_attrs.get(sig, ()):
                _append_attr(record, attr_key, attr_val)

        return final_spans
