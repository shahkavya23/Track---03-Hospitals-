"""Deterministic candidate generation for patient record linkage."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations, product
import time
import tracemalloc
from typing import Sequence

from src.contracts import PatientRecord


@dataclass(frozen=True, slots=True)
class CandidatePair:
    """A safe candidate pair containing references and reason codes only."""

    record_ref_a: str
    record_ref_b: str
    evidence_categories: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BlockingMetrics:
    """Measured effectiveness and resource use of candidate generation."""

    total_possible_pairs: int
    candidate_pairs: int
    true_match_pairs: int
    true_matches_recalled: int
    candidate_recall: float
    reduction_ratio: float
    elapsed_seconds: float
    peak_memory_bytes: int


def exact_attribute_pairs(
    records: Sequence[PatientRecord],
    attribute: str,
    max_bucket_size: int | None = None,
) -> list[CandidatePair]:
    """Return record pairs sharing an exact normalized attribute value.

    Attribute values are used only as in-memory bucket keys. They are never
    included in the returned objects.
    """

    buckets: dict[str, set[str]] = defaultdict(set)
    for record in records:
        for value in record.extracted_patient_attributes.get(attribute, []):
            normalized_value = value.strip()
            if normalized_value:
                buckets[normalized_value].add(record.record_ref)

    reason = f"EXACT_{attribute.upper()}"
    pairs: set[tuple[str, str]] = set()
    for record_refs in buckets.values():
        if max_bucket_size is not None and len(record_refs) > max_bucket_size:
            continue
        pairs.update(combinations(sorted(record_refs), 2))

    return [
        CandidatePair(left, right, (reason,))
        for left, right in sorted(pairs)
    ]


def typed_identifier_pairs(
    records: Sequence[PatientRecord],
    attribute: str = "ids",
    max_bucket_size: int | None = None,
) -> list[CandidatePair]:
    """Block on canonical IDs formatted as ``TYPE|[ISSUER|]VALUE``.

    The issuer component prevents hospital-local IDs such as UHID or MRN
    values from colliding across different hospitals.
    """

    buckets: dict[str, set[str]] = defaultdict(set)
    identifier_types: dict[str, str] = {}
    for record in records:
        for identifier in record.extracted_patient_attributes.get(attribute, []):
            parts = [part.strip() for part in identifier.split("|")]
            if len(parts) < 2 or any(not part for part in parts):
                continue
            identifier_type = parts[0].upper()
            canonical_identifier = "|".join([identifier_type, *parts[1:]])
            buckets[canonical_identifier].add(record.record_ref)
            identifier_types[canonical_identifier] = identifier_type

    evidence_by_pair: dict[tuple[str, str], set[str]] = defaultdict(set)
    for canonical_identifier, record_refs in buckets.items():
        if max_bucket_size is not None and len(record_refs) > max_bucket_size:
            continue
        reason = f"EXACT_ID_{identifier_types[canonical_identifier]}"
        for pair in combinations(sorted(record_refs), 2):
            evidence_by_pair[pair].add(reason)

    return [
        CandidatePair(left, right, tuple(sorted(evidence_categories)))
        for (left, right), evidence_categories in sorted(evidence_by_pair.items())
    ]


def exact_compound_attribute_pairs(
    records: Sequence[PatientRecord],
    attributes: Sequence[str],
    evidence_category: str,
    max_bucket_size: int | None = None,
) -> list[CandidatePair]:
    """Block records only when every normalized attribute in a group matches."""

    buckets: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for record in records:
        value_groups: list[tuple[str, ...]] = []
        for attribute in attributes:
            values = tuple(
                sorted(
                    {
                        value.strip()
                        for value in record.extracted_patient_attributes.get(attribute, [])
                        if value.strip()
                    }
                )
            )
            if not values:
                break
            value_groups.append(values)
        else:
            for compound_key in product(*value_groups):
                buckets[compound_key].add(record.record_ref)

    pairs: set[tuple[str, str]] = set()
    for record_refs in buckets.values():
        if max_bucket_size is not None and len(record_refs) > max_bucket_size:
            continue
        pairs.update(combinations(sorted(record_refs), 2))

    return [
        CandidatePair(left, right, (evidence_category,))
        for left, right in sorted(pairs)
    ]


def exact_name_dob_pairs(
    records: Sequence[PatientRecord], max_bucket_size: int | None = None
) -> list[CandidatePair]:
    """Return candidates sharing both normalized patient name and full DOB."""

    return exact_compound_attribute_pairs(
        records,
        attributes=("names", "dobs"),
        evidence_category="EXACT_NAME_DOB",
        max_bucket_size=max_bucket_size,
    )


def normalized_name_birth_year_pairs(
    records: Sequence[PatientRecord],
    max_bucket_size: int | None = None,
) -> list[CandidatePair]:
    """Block on a cross-script/phonetic name key plus compatible birth year."""

    return exact_compound_attribute_pairs(
        records,
        attributes=("name_keys", "birth_years"),
        evidence_category="NAME_KEY_BIRTH_YEAR",
        max_bucket_size=max_bucket_size,
    )


def relative_geography_pairs(
    records: Sequence[PatientRecord], max_bucket_size: int | None = None
) -> list[CandidatePair]:
    """Block on normalized relative-name and geography keys together."""

    return exact_compound_attribute_pairs(
        records,
        attributes=("relative_name_keys", "geo_keys"),
        evidence_category="RELATIVE_GEO_KEY",
        max_bucket_size=max_bucket_size,
    )


def combine_exact_attribute_blocks(
    records: Sequence[PatientRecord],
    attributes: Sequence[str],
    max_bucket_size: int | None = None,
) -> list[CandidatePair]:
    """Combine exact-match blocks without returning duplicate record pairs."""

    evidence_by_pair: dict[tuple[str, str], set[str]] = defaultdict(set)
    for attribute in attributes:
        attribute_pairs = (
            typed_identifier_pairs(records, attribute, max_bucket_size)
            if attribute == "ids"
            else exact_attribute_pairs(records, attribute, max_bucket_size)
        )
        for pair in attribute_pairs:
            key = (pair.record_ref_a, pair.record_ref_b)
            evidence_by_pair[key].update(pair.evidence_categories)

    return [
        CandidatePair(left, right, tuple(sorted(evidence_categories)))
        for (left, right), evidence_categories in sorted(evidence_by_pair.items())
    ]


def generate_candidate_pairs(
    records: Sequence[PatientRecord], max_bucket_size: int = 100
) -> list[CandidatePair]:
    """Run all blocking passes and merge their safe evidence categories."""

    evidence_by_pair: dict[tuple[str, str], set[str]] = defaultdict(set)
    blocking_passes = (
        exact_attribute_pairs(records, "phones", max_bucket_size),
        typed_identifier_pairs(records, max_bucket_size=max_bucket_size),
        exact_name_dob_pairs(records, max_bucket_size),
        normalized_name_birth_year_pairs(records, max_bucket_size),
        relative_geography_pairs(records, max_bucket_size),
    )
    for candidate_pairs in blocking_passes:
        for pair in candidate_pairs:
            key = (pair.record_ref_a, pair.record_ref_b)
            evidence_by_pair[key].update(pair.evidence_categories)

    return [
        CandidatePair(left, right, tuple(sorted(evidence_categories)))
        for (left, right), evidence_categories in sorted(evidence_by_pair.items())
    ]


def evaluate_candidate_generation(
    records: Sequence[PatientRecord],
    true_match_pairs: set[tuple[str, str]],
    max_bucket_size: int = 100,
) -> tuple[list[CandidatePair], BlockingMetrics]:
    """Run blocking and report measured recall, reduction, time, and memory."""

    started_tracing = not tracemalloc.is_tracing()
    if started_tracing:
        tracemalloc.start()
    started_at = time.perf_counter()
    candidates = generate_candidate_pairs(records, max_bucket_size)
    elapsed_seconds = time.perf_counter() - started_at
    _, peak_memory_bytes = tracemalloc.get_traced_memory()
    if started_tracing:
        tracemalloc.stop()

    normalized_truth = {
        tuple(sorted(pair)) for pair in true_match_pairs if pair[0] != pair[1]
    }
    candidate_keys = {
        (pair.record_ref_a, pair.record_ref_b) for pair in candidates
    }
    recalled = len(candidate_keys & normalized_truth)
    record_count = len({record.record_ref for record in records})
    total_possible_pairs = record_count * (record_count - 1) // 2
    recall = recalled / len(normalized_truth) if normalized_truth else 1.0
    reduction = (
        1.0 - (len(candidate_keys) / total_possible_pairs)
        if total_possible_pairs
        else 0.0
    )

    return candidates, BlockingMetrics(
        total_possible_pairs=total_possible_pairs,
        candidate_pairs=len(candidate_keys),
        true_match_pairs=len(normalized_truth),
        true_matches_recalled=recalled,
        candidate_recall=recall,
        reduction_ratio=reduction,
        elapsed_seconds=elapsed_seconds,
        peak_memory_bytes=peak_memory_bytes,
    )
