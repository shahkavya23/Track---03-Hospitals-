"""Constraint-aware clustering that prevents transitive patient over-merging."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from itertools import combinations
from typing import Mapping, Sequence

from src.contracts import (
    LinkageDecision,
    LinkageVerdict,
    PatientCluster,
    PatientRecord,
    ResolutionStatus,
)


@dataclass(frozen=True, slots=True)
class RejectedMerge:
    """A safe explanation for a MATCH edge rejected at cluster level."""

    record_ref_a: str
    record_ref_b: str
    reason: str


@dataclass(frozen=True, slots=True)
class ClusteringResult:
    """Clusters plus safe audit information about rejected merge attempts."""

    clusters: tuple[PatientCluster, ...]
    rejected_merges: tuple[RejectedMerge, ...]


@dataclass(frozen=True, slots=True)
class ClusteringMetrics:
    """Pairwise cluster-quality measurements against synthetic truth."""

    pairwise_precision: float
    pairwise_recall: float
    false_merge_rate: float
    false_split_rate: float
    cluster_consistency: float


def _pair(left_ref: str, right_ref: str) -> tuple[str, str]:
    return tuple(sorted((left_ref, right_ref)))


def _consolidate_decisions(
    decisions: Sequence[LinkageDecision],
) -> dict[tuple[str, str], tuple[LinkageVerdict, float]]:
    """Fail closed when duplicate decisions disagree."""

    grouped: dict[tuple[str, str], list[LinkageDecision]] = {}
    for decision in decisions:
        if decision.record_ref_a == decision.record_ref_b:
            continue
        grouped.setdefault(
            _pair(decision.record_ref_a, decision.record_ref_b), []
        ).append(decision)

    consolidated: dict[tuple[str, str], tuple[LinkageVerdict, float]] = {}
    for pair, pair_decisions in grouped.items():
        verdicts = {decision.decision for decision in pair_decisions}
        if LinkageVerdict.NON_MATCH in verdicts:
            consolidated[pair] = (
                LinkageVerdict.NON_MATCH,
                min(decision.score for decision in pair_decisions),
            )
        elif verdicts == {LinkageVerdict.MATCH}:
            consolidated[pair] = (
                LinkageVerdict.MATCH,
                max(decision.score for decision in pair_decisions),
            )
        else:
            consolidated[pair] = (
                LinkageVerdict.ABSTAIN,
                max(decision.score for decision in pair_decisions),
            )
    return consolidated


def _record_identity_status(record: PatientRecord) -> ResolutionStatus:
    """Classify a singleton using only stable, normalized identity anchors."""

    namespaces: dict[tuple[str, ...], set[str]] = {}
    for identifier in record.extracted_patient_attributes.get("ids", []):
        parts = tuple(part.strip() for part in identifier.split("|"))
        if len(parts) == 2 and all(parts):
            namespace, value = (parts[0].upper(),), parts[1]
        elif len(parts) == 3 and all(parts):
            namespace, value = (parts[0].upper(), parts[1].upper()), parts[2]
        else:
            continue
        namespaces.setdefault(namespace, set()).add(value)

    if any(len(values) > 1 for values in namespaces.values()):
        return ResolutionStatus.CONFLICT
    if namespaces:
        return ResolutionStatus.RESOLVED

    phones = {
        value.strip()
        for value in record.extracted_patient_attributes.get("phones", [])
        if value.strip()
    }
    dobs = {
        value.strip()
        for value in record.extracted_patient_attributes.get("dobs", [])
        if value.strip()
    }
    if phones and dobs:
        return ResolutionStatus.RESOLVED
    return ResolutionStatus.UNRESOLVED


def _cluster_ref(member_record_refs: Sequence[str]) -> str:
    canonical_members = "\0".join(sorted(member_record_refs)).encode("utf-8")
    digest = hashlib.sha256(b"raksha:cluster:v1\0" + canonical_members).hexdigest()[:16]
    return f"clu_{digest}"


def cluster_records(
    records: Sequence[PatientRecord],
    decisions: Sequence[LinkageDecision],
) -> ClusteringResult:
    """Build deterministic complete-link clusters with cannot-link constraints."""

    records_by_ref = {record.record_ref: record for record in records}
    if len(records_by_ref) != len(records):
        raise ValueError("PatientRecord record_ref values must be unique")

    pair_decisions = _consolidate_decisions(decisions)
    for left_ref, right_ref in pair_decisions:
        if left_ref not in records_by_ref or right_ref not in records_by_ref:
            raise ValueError("LinkageDecision references an unknown record")

    parent = {record_ref: record_ref for record_ref in records_by_ref}
    members = {record_ref: {record_ref} for record_ref in records_by_ref}

    def find(record_ref: str) -> str:
        while parent[record_ref] != record_ref:
            parent[record_ref] = parent[parent[record_ref]]
            record_ref = parent[record_ref]
        return record_ref

    match_edges = sorted(
        (
            (-score, left_ref, right_ref)
            for (left_ref, right_ref), (verdict, score) in pair_decisions.items()
            if verdict == LinkageVerdict.MATCH
        )
    )
    rejected: list[RejectedMerge] = []
    for _, left_ref, right_ref in match_edges:
        left_root, right_root = find(left_ref), find(right_ref)
        if left_root == right_root:
            continue

        cross_verdicts = [
            pair_decisions.get(_pair(left_member, right_member))
            for left_member in members[left_root]
            for right_member in members[right_root]
        ]
        if any(
            item is not None and item[0] == LinkageVerdict.NON_MATCH
            for item in cross_verdicts
        ):
            rejected.append(RejectedMerge(left_ref, right_ref, "CANNOT_LINK"))
            continue
        if any(
            item is None or item[0] != LinkageVerdict.MATCH
            for item in cross_verdicts
        ):
            rejected.append(
                RejectedMerge(left_ref, right_ref, "INCOMPLETE_PAIRWISE_SUPPORT")
            )
            continue

        new_root, old_root = sorted((left_root, right_root))
        parent[old_root] = new_root
        members[new_root].update(members.pop(old_root))

    grouped_members = sorted(
        (tuple(sorted(group)) for group in members.values()),
        key=lambda group: group,
    )
    clusters: list[PatientCluster] = []
    for member_refs in grouped_members:
        if len(member_refs) > 1:
            status = ResolutionStatus.RESOLVED
        else:
            status = _record_identity_status(records_by_ref[member_refs[0]])
        cluster_ref = _cluster_ref(member_refs)
        cluster = PatientCluster(
            cluster_ref=cluster_ref,
            member_record_refs=member_refs,
            resolution_status=status,
        )
        clusters.append(cluster)
        for member_ref in member_refs:
            records_by_ref[member_ref].cluster_ref = cluster_ref

    return ClusteringResult(
        clusters=tuple(clusters),
        rejected_merges=tuple(
            sorted(rejected, key=lambda item: (item.record_ref_a, item.record_ref_b, item.reason))
        ),
    )


def evaluate_clustering(
    result: ClusteringResult,
    true_patient_by_record: Mapping[str, str],
) -> ClusteringMetrics:
    """Measure false merges, false splits, and cluster consistency."""

    predicted_pairs: set[tuple[str, str]] = set()
    for cluster in result.clusters:
        predicted_pairs.update(combinations(cluster.member_record_refs, 2))

    truth_groups: dict[str, set[str]] = {}
    for record_ref, patient_ref in true_patient_by_record.items():
        truth_groups.setdefault(patient_ref, set()).add(record_ref)
    truth_pairs: set[tuple[str, str]] = set()
    for group in truth_groups.values():
        truth_pairs.update(combinations(sorted(group), 2))

    true_positives = len(predicted_pairs & truth_pairs)
    false_positives = len(predicted_pairs - truth_pairs)
    false_negatives = len(truth_pairs - predicted_pairs)
    precision = true_positives / len(predicted_pairs) if predicted_pairs else 1.0
    recall = true_positives / len(truth_pairs) if truth_pairs else 1.0

    consistent_clusters = 0
    evaluated_clusters = 0
    for cluster in result.clusters:
        truth_labels = {
            true_patient_by_record[member_ref]
            for member_ref in cluster.member_record_refs
            if member_ref in true_patient_by_record
        }
        if truth_labels:
            evaluated_clusters += 1
            if len(truth_labels) == 1:
                consistent_clusters += 1

    return ClusteringMetrics(
        pairwise_precision=precision,
        pairwise_recall=recall,
        false_merge_rate=(
            false_positives / len(predicted_pairs) if predicted_pairs else 0.0
        ),
        false_split_rate=(
            false_negatives / len(truth_pairs) if truth_pairs else 0.0
        ),
        cluster_consistency=(
            consistent_clusters / evaluated_clusters if evaluated_clusters else 1.0
        ),
    )
