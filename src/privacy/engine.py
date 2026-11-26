"""Integrated Member 3 privacy engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.contracts import (
    PatientCluster,
    PatientRecord,
    PrivacyDecision,
    ResolutionStatus,
    SpanRole,
    TransformType,
)
from src.privacy.date_shift import DateShiftMetrics, PatientDateShifter
from src.privacy.generalization import AdaptiveGeneralizer, GeneralizationMetrics
from src.privacy.pseudonymization import HMACPseudonymizer, PseudonymizationMetrics


@dataclass(frozen=True, slots=True)
class PrivacyEngineMetrics:
    pseudonymization: PseudonymizationMetrics
    date_shifting: DateShiftMetrics
    generalization: GeneralizationMetrics


def _unresolved_reason(record: PatientRecord, status: ResolutionStatus) -> str:
    """Return a safe explanation code without exposing identity evidence."""
    if status == ResolutionStatus.CONFLICT:
        return "CONFLICTING_IDENTITY_EVIDENCE"

    has_identifier = any(
        value.strip()
        for value in record.extracted_patient_attributes.get("ids", [])
    )
    has_phone = any(
        value.strip()
        for value in record.extracted_patient_attributes.get("phones", [])
    )
    has_dob = any(
        value.strip()
        for value in record.extracted_patient_attributes.get("dobs", [])
    )
    has_name = any(
        value.strip()
        for value in record.extracted_patient_attributes.get("name_keys", [])
    )

    if has_phone and not has_dob and not has_identifier:
        return "PHONE_WITHOUT_DOB_OR_STABLE_ID"
    if has_dob and not has_phone and not has_identifier:
        return "DOB_WITHOUT_PHONE_OR_STABLE_ID"
    if has_name and not has_identifier:
        return "NAME_WITHOUT_ENOUGH_SUPPORTING_EVIDENCE"
    return "INSUFFICIENT_IDENTITY_EVIDENCE"


def _unresolved_identifier_decisions(
    records: Sequence[PatientRecord],
    clusters: Sequence[PatientCluster],
) -> list[PrivacyDecision]:
    """Redact direct PII with a safe reason when no pseudonym can be assigned."""
    status_by_record = {
        record_ref: cluster.resolution_status
        for cluster in clusters
        for record_ref in cluster.member_record_refs
    }
    decisions: list[PrivacyDecision] = []
    for record in records:
        if record.pseudonym_id is not None:
            continue
        status = status_by_record.get(
            record.record_ref, ResolutionStatus.UNRESOLVED
        )
        replacement = f"[UNRESOLVED: {_unresolved_reason(record, status)}]"
        for span in record.detections:
            if span.role != SpanRole.DIRECT_PII:
                continue
            decisions.append(
                PrivacyDecision(
                    record_ref=record.record_ref,
                    field_path=span.field_path,
                    start=span.start,
                    end=span.end,
                    transform_type=TransformType.REDACT,
                    replacement_value=replacement,
                )
            )
    return decisions


class AdaptivePrivacyEngine:
    """Protocol-compatible pseudonymization, date-shift, and QI privacy stage."""

    def __init__(self) -> None:
        self.pseudonymizer = HMACPseudonymizer()
        self.date_shifter = PatientDateShifter()
        self.generalizer = AdaptiveGeneralizer()
        self.last_metrics: PrivacyEngineMetrics | None = None

    def transform(
        self,
        records: Sequence[PatientRecord],
        clusters: Sequence[PatientCluster],
        secret_key: bytes,
    ) -> list[PrivacyDecision]:
        decisions = self.pseudonymizer.transform(records, clusters, secret_key)
        decisions.extend(_unresolved_identifier_decisions(records, clusters))
        decisions.extend(self.date_shifter.transform(records, clusters, secret_key))
        decisions.extend(self.generalizer.transform(records))
        decisions.sort(
            key=lambda item: (
                item.record_ref,
                item.field_path,
                -1 if item.start is None else item.start,
                item.transform_type,
            )
        )
        assert self.pseudonymizer.last_metrics is not None
        assert self.date_shifter.last_metrics is not None
        assert self.generalizer.last_metrics is not None
        self.last_metrics = PrivacyEngineMetrics(
            pseudonymization=self.pseudonymizer.last_metrics,
            date_shifting=self.date_shifter.last_metrics,
            generalization=self.generalizer.last_metrics,
        )
        return decisions
