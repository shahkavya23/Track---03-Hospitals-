"""Adversarial privacy evaluation and security regression helpers."""

from .attacker_simulator import (
    SyntheticProfile,
    evaluate_utility,
    measure_k_anonymity,
    measure_l_diversity,
    simulate_linkage_attack,
)
from .leakage import assert_no_leaks, scan_for_leaks
from .validation import benchmark_member3_pipeline, validate_member3_state

__all__ = [
    "SyntheticProfile",
    "assert_no_leaks",
    "benchmark_member3_pipeline",
    "evaluate_utility",
    "measure_k_anonymity",
    "measure_l_diversity",
    "simulate_linkage_attack",
    "scan_for_leaks",
    "validate_member3_state",
]
