"""Controlled re-identification attacks using synthetic profiles only."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class SyntheticProfile:
    subject_ref: str
    attributes: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class AttackMetrics:
    targets: int
    uniquely_reidentified: int
    correct_unique_matches: int
    attack_success_rate: float
    average_candidate_set_size: float
    expected_prosecutor_success: float


@dataclass(frozen=True, slots=True)
class KAnonymityMetrics:
    records: int
    minimum_k: int
    unique_profiles: int


@dataclass(frozen=True, slots=True)
class LDiversityMetrics:
    equivalence_classes: int
    minimum_l: int


@dataclass(frozen=True, slots=True)
class UtilityMetrics:
    compared_records: int
    age_containment_rate: float
    diagnosis_retention_rate: float
    stay_length_retention_rate: float


def _key(profile: SyntheticProfile, fields: Sequence[str]) -> tuple[str, ...]:
    return tuple(profile.attributes.get(field, "<MISSING>") for field in fields)


def simulate_linkage_attack(
    released_profiles: Sequence[SyntheticProfile],
    external_profiles: Sequence[SyntheticProfile],
    known_fields: Sequence[str],
) -> AttackMetrics:
    """Attempt exact linkage using only the attacker's declared knowledge."""

    released_by_key: dict[tuple[str, ...], list[SyntheticProfile]] = defaultdict(list)
    for profile in released_profiles:
        released_by_key[_key(profile, known_fields)].append(profile)

    candidate_sizes: list[int] = []
    unique_matches = 0
    correct_unique_matches = 0
    expected_success = 0.0
    for external in external_profiles:
        candidates = released_by_key.get(_key(external, known_fields), [])
        candidate_sizes.append(len(candidates))
        if candidates:
            expected_success += 1.0 / len(candidates)
        if len(candidates) == 1:
            unique_matches += 1
            if candidates[0].subject_ref == external.subject_ref:
                correct_unique_matches += 1

    targets = len(external_profiles)
    return AttackMetrics(
        targets=targets,
        uniquely_reidentified=unique_matches,
        correct_unique_matches=correct_unique_matches,
        attack_success_rate=correct_unique_matches / targets if targets else 0.0,
        average_candidate_set_size=(sum(candidate_sizes) / targets if targets else 0.0),
        expected_prosecutor_success=(expected_success / targets if targets else 0.0),
    )


def measure_k_anonymity(
    profiles: Sequence[SyntheticProfile], qi_fields: Sequence[str]
) -> KAnonymityMetrics:
    counts = Counter(_key(profile, qi_fields) for profile in profiles)
    return KAnonymityMetrics(
        records=len(profiles),
        minimum_k=min(counts.values()) if counts else 0,
        unique_profiles=sum(count == 1 for count in counts.values()),
    )


def measure_l_diversity(
    profiles: Sequence[SyntheticProfile],
    qi_fields: Sequence[str],
    sensitive_field: str,
) -> LDiversityMetrics:
    sensitive_values: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for profile in profiles:
        sensitive_values[_key(profile, qi_fields)].add(
            profile.attributes.get(sensitive_field, "<MISSING>")
        )
    diversity = [len(values) for values in sensitive_values.values()]
    return LDiversityMetrics(
        equivalence_classes=len(diversity),
        minimum_l=min(diversity) if diversity else 0,
    )


def _age_is_contained(exact_age: str, released_age: str) -> bool:
    try:
        age = int(exact_age)
    except ValueError:
        return False
    if released_age.endswith("+"):
        try:
            return age >= int(released_age[:-1])
        except ValueError:
            return False
    if "-" in released_age:
        try:
            lower, upper = (int(value) for value in released_age.split("-", 1))
        except ValueError:
            return False
        return lower <= age <= upper
    return released_age == exact_age


def evaluate_utility(
    original_profiles: Sequence[SyntheticProfile],
    released_profiles: Sequence[SyntheticProfile],
) -> UtilityMetrics:
    released_by_ref = {profile.subject_ref: profile for profile in released_profiles}
    comparable = [
        (original, released_by_ref[original.subject_ref])
        for original in original_profiles
        if original.subject_ref in released_by_ref
    ]
    if not comparable:
        return UtilityMetrics(0, 0.0, 0.0, 0.0)

    age_contained = sum(
        _age_is_contained(
            original.attributes.get("age", ""),
            released.attributes.get("age", ""),
        )
        for original, released in comparable
    )
    diagnosis_retained = sum(
        original.attributes.get("diagnosis") == released.attributes.get("diagnosis")
        for original, released in comparable
    )
    stay_retained = sum(
        original.attributes.get("stay_length") == released.attributes.get("stay_length")
        for original, released in comparable
    )
    count = len(comparable)
    return UtilityMetrics(
        compared_records=count,
        age_containment_rate=age_contained / count,
        diagnosis_retention_rate=diagnosis_retained / count,
        stay_length_retention_rate=stay_retained / count,
    )
