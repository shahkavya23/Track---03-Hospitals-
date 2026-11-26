"""HMAC pseudonymization and quasi-identifier privacy layer."""

from .engine import AdaptivePrivacyEngine, PrivacyEngineMetrics
from .date_shift import PatientDateShifter, derive_date_offset, shift_date_value
from .generalization import AdaptiveGeneralizer, GeneralizationPolicy
from .pseudonymization import (
    HMACPseudonymizer,
    PseudonymizationMetrics,
    assign_cluster_pseudonyms,
)

__all__ = [
    "AdaptivePrivacyEngine",
    "AdaptiveGeneralizer",
    "GeneralizationPolicy",
    "HMACPseudonymizer",
    "PatientDateShifter",
    "PrivacyEngineMetrics",
    "PseudonymizationMetrics",
    "assign_cluster_pseudonyms",
    "derive_date_offset",
    "shift_date_value",
]
