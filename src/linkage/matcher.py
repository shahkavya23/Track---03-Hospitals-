"""Transparent, conservative pairwise patient-record matching."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import time
import tracemalloc
from typing import Sequence

from src.contracts import LinkageDecision, LinkageVerdict, PatientRecord
from src.linkage.blocking import CandidatePair


STRONG_GLOBAL_ID_TYPES = frozenset({"ABHA", "AADHAAR", "PAN"})
LOCAL_ID_TYPES = frozenset({"UHID", "MRN", "INSURANCE"})


@dataclass(frozen=True, slots=True)
class MatcherPolicy:
    """Configurable evidence weights and conservative decision thresholds."""

    match_threshold: float = 0.8
    non_match_threshold: float = -0.5
    fuzzy_name_threshold: float = 0.88
    phone_weight: float = 0.4
    dob_weight: float = 0.5
    exact_name_key_weight: float = 0.25
    fuzzy_name_weight: float = 0.2
    birth_year_weight: float = 0.15
    relative_name_weight: float = 0.2
    geography_weight: float = 0.2
    local_id_weight: float = 0.6

    def __post_init__(self) -> None:
        if not -1.0 <= self.non_match_threshold < self.match_threshold <= 1.0:
            raise ValueError("Matcher thresholds must be ordered within [-1, 1]")
        if not 0.0 <= self.fuzzy_name_threshold <= 1.0:
            raise ValueError("Fuzzy-name threshold must be within [0, 1]")


@dataclass(frozen=True, slots=True)
class MatchingMetrics:
    """Measured pairwise quality, abstention, time, and memory."""

    decisions_total: int
    matches: int
    non_matches: int
    abstentions: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    false_merge_rate: float
    abstention_rate: float
    elapsed_seconds: float
    peak_memory_bytes: int


def _values(record: PatientRecord, attribute: str) -> set[str]:
    return {
        value.strip()
        for value in record.extracted_patient_attributes.get(attribute, [])
        if value.strip()
    }


def _identifiers(
    record: PatientRecord,
) -> tuple[dict[str, set[str]], dict[tuple[str, str], set[str]]]:
    """Parse canonical IDs; malformed values are ignored without exposure."""

    global_ids: dict[str, set[str]] = {}
    local_ids: dict[tuple[str, str], set[str]] = {}
    for identifier in record.extracted_patient_attributes.get("ids", []):
        parts = [part.strip() for part in identifier.split("|")]
        if not parts:
            continue
        identifier_type = parts[0].upper()
        if identifier_type in STRONG_GLOBAL_ID_TYPES and len(parts) == 2 and parts[1]:
            global_ids.setdefault(identifier_type, set()).add(parts[1])
        elif (
            identifier_type in LOCAL_ID_TYPES
            and len(parts) == 3
            and parts[1]
            and parts[2]
        ):
            namespace = (identifier_type, parts[1].upper())
            local_ids.setdefault(namespace, set()).add(parts[2])
    return global_ids, local_ids


def _best_fuzzy_name_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return max(
        SequenceMatcher(None, left_name.casefold(), right_name.casefold()).ratio()
        for left_name in sorted(left)
        for right_name in sorted(right)
    )


def _decision(
    left: PatientRecord,
    right: PatientRecord,
    verdict: LinkageVerdict,
    score: float,
    evidence_categories: Sequence[str],
) -> LinkageDecision:
    record_ref_a, record_ref_b = sorted((left.record_ref, right.record_ref))
    return LinkageDecision(
        record_ref_a=record_ref_a,
        record_ref_b=record_ref_b,
        decision=verdict,
        score=round(score, 4),
        evidence_categories=tuple(sorted(set(evidence_categories))),
    )


def match_pair(
    left: PatientRecord,
    right: PatientRecord,
    policy: MatcherPolicy | None = None,
) -> LinkageDecision:
    """Classify one pair as MATCH, NON_MATCH, or ABSTAIN."""

    policy = policy or MatcherPolicy()
    left_global, left_local = _identifiers(left)
    right_global, right_local = _identifiers(right)

    ambiguous_ids = sorted(
        {
            f"AMBIGUOUS_ID_{identifier_type}"
            for identifier_type, values in (*left_global.items(), *right_global.items())
            if len(values) > 1
        }
        | {
            f"AMBIGUOUS_ID_{identifier_type}"
            for (identifier_type, _), values in (*left_local.items(), *right_local.items())
            if len(values) > 1
        }
    )
    if ambiguous_ids:
        return _decision(left, right, LinkageVerdict.ABSTAIN, 0.0, ambiguous_ids)

    shared_global_types = sorted(set(left_global) & set(right_global))
    conflicting_global_types = [
        identifier_type
        for identifier_type in shared_global_types
        if left_global[identifier_type].isdisjoint(right_global[identifier_type])
    ]
    if conflicting_global_types:
        return _decision(
            left,
            right,
            LinkageVerdict.NON_MATCH,
            -1.0,
            [f"CONFLICT_ID_{item}" for item in conflicting_global_types],
        )

    matching_global_types = [
        identifier_type
        for identifier_type in shared_global_types
        if left_global[identifier_type] & right_global[identifier_type]
    ]

    left_phones = _values(left, "phones")
    right_phones = _values(right, "phones")
    left_dobs = _values(left, "dobs")
    right_dobs = _values(right, "dobs")
    shared_phones = left_phones & right_phones
    shared_dobs = left_dobs & right_dobs
    dob_conflict = bool(left_dobs and right_dobs and not shared_dobs)

    left_genders = _values(left, "genders")
    right_genders = _values(right, "genders")
    if left_genders and right_genders and left_genders.isdisjoint(right_genders):
        return _decision(left, right, LinkageVerdict.NON_MATCH, -1.0, ("CONFLICT_SEX",))

    left_ages = {int(v) for v in _values(left, "ages") if v.isdigit()}
    right_ages = {int(v) for v in _values(right, "ages") if v.isdigit()}
    if left_ages and right_ages and min(abs(a - b) for a in left_ages for b in right_ages) > 5:
        return _decision(left, right, LinkageVerdict.NON_MATCH, -1.0, ("CONFLICT_AGE",))

    left_names = _values(left, "name_keys")
    right_names = _values(right, "name_keys")
    left_relatives = _values(left, "relative_name_keys")
    right_relatives = _values(right, "relative_name_keys")
    if (left_names & right_relatives) or (right_names & left_relatives):
        return _decision(left, right, LinkageVerdict.NON_MATCH, -1.0, ("STATED_FAMILY_RELATION",))
    if shared_dobs and left_relatives & right_relatives and left_names and right_names and left_names.isdisjoint(right_names):
        return _decision(left, right, LinkageVerdict.NON_MATCH, -1.0, ("POSSIBLE_TWINS",))

    if matching_global_types:
        evidence = [f"EXACT_ID_{item}" for item in matching_global_types]
        if dob_conflict:
            evidence.append("CONFLICT_DOB")
            return _decision(left, right, LinkageVerdict.ABSTAIN, 0.0, evidence)
        return _decision(left, right, LinkageVerdict.MATCH, 1.0, evidence)

    shared_local_namespaces = sorted(set(left_local) & set(right_local))
    conflicting_local_types = [
        identifier_type
        for identifier_type, issuer in shared_local_namespaces
        if left_local[(identifier_type, issuer)].isdisjoint(
            right_local[(identifier_type, issuer)]
        )
    ]
    if conflicting_local_types:
        return _decision(
            left,
            right,
            LinkageVerdict.NON_MATCH,
            -0.7,
            [f"CONFLICT_ID_{item}" for item in conflicting_local_types],
        )

    matching_local_types = sorted(
        {
            identifier_type
            for identifier_type, issuer in shared_local_namespaces
            if left_local[(identifier_type, issuer)]
            & right_local[(identifier_type, issuer)]
        }
    )

    if shared_phones and dob_conflict:
        return _decision(
            left,
            right,
            LinkageVerdict.NON_MATCH,
            -0.8,
            ("CONFLICT_DOB", "EXACT_PHONE"),
        )

    exact_name = bool(left_names & right_names)
    fuzzy_name = _best_fuzzy_name_similarity(left_names, right_names) >= policy.fuzzy_name_threshold
    shared_birth_year = bool(_values(left, "birth_years") & _values(right, "birth_years"))
    identity_agreement = exact_name or fuzzy_name or bool(shared_dobs) or shared_birth_year

    score = 0.0
    evidence: list[str] = []
    if matching_local_types:
        score += policy.local_id_weight
        evidence.extend(f"EXACT_ID_{item}" for item in matching_local_types)
    if shared_phones and identity_agreement:
        score += policy.phone_weight
        evidence.append("EXACT_PHONE")
    if shared_dobs:
        score += policy.dob_weight
        evidence.append("EXACT_DOB")

    if exact_name:
        score += policy.exact_name_key_weight
        evidence.append("NAME_KEY")
    elif (
        fuzzy_name
    ):
        score += policy.fuzzy_name_weight
        evidence.append("FUZZY_NAME")

    supporting_attributes = (
        ("birth_years", "BIRTH_YEAR", policy.birth_year_weight),
        ("relative_name_keys", "RELATIVE_NAME_KEY", policy.relative_name_weight),
        ("geo_keys", "GEO_KEY", policy.geography_weight),
    )
    for attribute, evidence_category, weight in supporting_attributes:
        if _values(left, attribute) & _values(right, attribute) and (
            attribute == "birth_years" or identity_agreement
        ):
            score += weight
            evidence.append(evidence_category)

    score = min(score, 1.0)
    if score >= policy.match_threshold:
        verdict = LinkageVerdict.MATCH
    elif score <= policy.non_match_threshold:
        verdict = LinkageVerdict.NON_MATCH
    else:
        verdict = LinkageVerdict.ABSTAIN
    return _decision(left, right, verdict, score, evidence)


def match_candidates(
    records: Sequence[PatientRecord],
    candidates: Sequence[CandidatePair],
    policy: MatcherPolicy | None = None,
) -> list[LinkageDecision]:
    """Deterministically classify a batch of unique candidate pairs."""

    records_by_ref = {record.record_ref: record for record in records}
    unique_pairs = sorted(
        {
            tuple(sorted((candidate.record_ref_a, candidate.record_ref_b)))
            for candidate in candidates
            if candidate.record_ref_a != candidate.record_ref_b
        }
    )
    decisions: list[LinkageDecision] = []
    for left_ref, right_ref in unique_pairs:
        if left_ref not in records_by_ref or right_ref not in records_by_ref:
            raise ValueError("Candidate pair references an unknown record")
        decisions.append(
            match_pair(records_by_ref[left_ref], records_by_ref[right_ref], policy)
        )
    return decisions


def evaluate_matching(
    records: Sequence[PatientRecord],
    candidates: Sequence[CandidatePair],
    true_match_pairs: set[tuple[str, str]],
    policy: MatcherPolicy | None = None,
) -> tuple[list[LinkageDecision], MatchingMetrics]:
    """Run batch matching and measure quality, abstention, time, and memory."""

    started_tracing = not tracemalloc.is_tracing()
    if started_tracing:
        tracemalloc.start()
    started_at = time.perf_counter()
    decisions = match_candidates(records, candidates, policy)
    elapsed_seconds = time.perf_counter() - started_at
    _, peak_memory_bytes = tracemalloc.get_traced_memory()
    if started_tracing:
        tracemalloc.stop()

    normalized_truth = {
        tuple(sorted(pair)) for pair in true_match_pairs if pair[0] != pair[1]
    }
    predicted_matches = {
        (decision.record_ref_a, decision.record_ref_b)
        for decision in decisions
        if decision.decision == LinkageVerdict.MATCH
    }
    true_positives = len(predicted_matches & normalized_truth)
    false_positives = len(predicted_matches - normalized_truth)
    false_negatives = len(normalized_truth - predicted_matches)
    matches = len(predicted_matches)
    non_matches = sum(
        decision.decision == LinkageVerdict.NON_MATCH for decision in decisions
    )
    abstentions = sum(
        decision.decision == LinkageVerdict.ABSTAIN for decision in decisions
    )
    precision = true_positives / matches if matches else 1.0
    recall = true_positives / len(normalized_truth) if normalized_truth else 1.0
    decisions_total = len(decisions)

    return decisions, MatchingMetrics(
        decisions_total=decisions_total,
        matches=matches,
        non_matches=non_matches,
        abstentions=abstentions,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        precision=precision,
        recall=recall,
        false_merge_rate=false_positives / matches if matches else 0.0,
        abstention_rate=abstentions / decisions_total if decisions_total else 0.0,
        elapsed_seconds=elapsed_seconds,
        peak_memory_bytes=peak_memory_bytes,
    )
