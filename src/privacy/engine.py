"""Integrated Member 3 privacy engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.contracts import PatientCluster, PatientRecord, PrivacyDecision
from src.privacy.date_shift import DateShiftMetrics, PatientDateShifter
from src.privacy.generalization import AdaptiveGeneralizer, GeneralizationMetrics
from src.privacy.pseudonymization import HMACPseudonymizer, PseudonymizationMetrics


@dataclass(frozen=True, slots=True)
class PrivacyEngineMetrics:
    pseudonymization: PseudonymizationMetrics
    date_shifting: DateShiftMetrics
    generalization: GeneralizationMetrics


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
