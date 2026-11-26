"""Integrated Member 3 privacy engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.contracts import (
    PatientCluster,
    PatientRecord,
    PrivacyDecision,
)
from src.privacy.date_shift import DateShiftMetrics, PatientDateShifter
from src.privacy.generalization import AdaptiveGeneralizer, GeneralizationMetrics, GeneralizationPolicy
from src.privacy.pseudonymization import HMACPseudonymizer, PseudonymizationMetrics
from src.privacy.structured import structure_aware_decisions


@dataclass(frozen=True, slots=True)
class PrivacyEngineMetrics:
    pseudonymization: PseudonymizationMetrics
    date_shifting: DateShiftMetrics
    generalization: GeneralizationMetrics


class AdaptivePrivacyEngine:
    """Protocol-compatible pseudonymization, date-shift, and QI privacy stage."""

    def __init__(
        self,
        *,
        k_threshold: int = 3,
        age_band_width: int = 5,
        age_top_code: int = 90,
        date_shift_max_days: int = 180,
        k_location: int = 5,
        household_shift: bool = True,
    ) -> None:
        self.pseudonymizer = HMACPseudonymizer()
        self.date_shifter = PatientDateShifter(max_abs_days=date_shift_max_days)
        self.generalizer = AdaptiveGeneralizer(GeneralizationPolicy(
            k_threshold=k_threshold,
            moderate_age_width=age_band_width,
            high_age_width=age_band_width,
        ))
        self.age_band_width = age_band_width
        self.age_top_code = age_top_code
        self.date_shift_max_days = date_shift_max_days
        self.k_location = k_location
        self.household_shift = household_shift
        self.last_metrics: PrivacyEngineMetrics | None = None

    def transform(
        self,
        records: Sequence[PatientRecord],
        clusters: Sequence[PatientCluster],
        secret_key: bytes,
    ) -> list[PrivacyDecision]:
        decisions = self.pseudonymizer.transform(records, clusters, secret_key)
        decisions.extend(structure_aware_decisions(
            records,
            secret_key,
            age_width=self.age_band_width,
            age_top_code=self.age_top_code,
            date_shift_max_days=self.date_shift_max_days,
            k_location=self.k_location,
            household_shift=self.household_shift,
        ))
        # Structure-aware shifting covers linked and singleton records, including
        # household coherence and export-date clamps.  Run the legacy shifter
        # only to retain its aggregate metrics without emitting duplicate edits.
        self.date_shifter.transform(records, clusters, secret_key)
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
