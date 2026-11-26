"""Synthetic re-identification attack and utility tests."""

from __future__ import annotations

import unittest

from src.security.attacker_simulator import (
    SyntheticProfile,
    evaluate_utility,
    measure_k_anonymity,
    measure_l_diversity,
    simulate_linkage_attack,
)


def _profile(subject_ref: str, **attributes: str) -> SyntheticProfile:
    return SyntheticProfile(subject_ref, attributes)


class AttackerSimulatorTests(unittest.TestCase):
    def test_generalization_reduces_unique_reidentification(self) -> None:
        external = [
            _profile("p1", age="47", gender="F", geography="Village A"),
            _profile("p2", age="48", gender="F", geography="Village B"),
            _profile("p3", age="49", gender="F", geography="Village C"),
        ]
        exact_release = list(external)
        generalized_release = [
            _profile(subject.subject_ref, age="45-49", gender="F", geography="Jaipur District")
            for subject in external
        ]
        generalized_external = [
            _profile(subject.subject_ref, age="45-49", gender="F", geography="Jaipur District")
            for subject in external
        ]

        before = simulate_linkage_attack(
            exact_release, external, ("age", "gender", "geography")
        )
        after = simulate_linkage_attack(
            generalized_release,
            generalized_external,
            ("age", "gender", "geography"),
        )

        self.assertEqual(before.attack_success_rate, 1.0)
        self.assertEqual(after.attack_success_rate, 0.0)
        self.assertEqual(after.average_candidate_set_size, 3.0)
        self.assertLess(after.expected_prosecutor_success, before.expected_prosecutor_success)

    def test_k_anonymity_and_l_diversity_are_measured(self) -> None:
        released = [
            _profile("p1", age="45-49", district="Jaipur", diagnosis="dengue"),
            _profile("p2", age="45-49", district="Jaipur", diagnosis="malaria"),
            _profile("p3", age="45-49", district="Jaipur", diagnosis="typhoid"),
        ]

        k_metrics = measure_k_anonymity(released, ("age", "district"))
        l_metrics = measure_l_diversity(
            released, ("age", "district"), "diagnosis"
        )

        self.assertEqual(k_metrics.minimum_k, 3)
        self.assertEqual(k_metrics.unique_profiles, 0)
        self.assertEqual(l_metrics.minimum_l, 3)

    def test_rare_diagnosis_can_still_break_anonymity(self) -> None:
        released = [
            _profile("p1", age="45-49", district="Jaipur", diagnosis="common"),
            _profile("p2", age="45-49", district="Jaipur", diagnosis="common"),
            _profile("p3", age="45-49", district="Jaipur", diagnosis="rare-x"),
        ]
        external = [_profile("p3", age="45-49", district="Jaipur", diagnosis="rare-x")]

        attack = simulate_linkage_attack(
            released, external, ("age", "district", "diagnosis")
        )

        self.assertEqual(attack.attack_success_rate, 1.0)


class UtilityMeasurementTests(unittest.TestCase):
    def test_age_diagnosis_and_stay_utility_are_measured(self) -> None:
        original = [
            _profile("p1", age="47", diagnosis="dengue", stay_length="9"),
            _profile("p2", age="92", diagnosis="malaria", stay_length="3"),
        ]
        released = [
            _profile("p1", age="45-49", diagnosis="dengue", stay_length="9"),
            _profile("p2", age="90+", diagnosis="malaria", stay_length="3"),
        ]

        utility = evaluate_utility(original, released)

        self.assertEqual(utility.age_containment_rate, 1.0)
        self.assertEqual(utility.diagnosis_retention_rate, 1.0)
        self.assertEqual(utility.stay_length_retention_rate, 1.0)


if __name__ == "__main__":
    unittest.main()
