"""Final Member 3 invariants and bounded performance measurement."""

from __future__ import annotations

from dataclasses import dataclass
import time
import tracemalloc
from typing import Sequence

from src.contracts import (
    PatientCluster,
    PatientRecord,
    PrivacyDecision,
    ResolutionStatus,
    SpanRole,
)
from src.linkage.engine import ConservativeLinkageEngine
from src.privacy import AdaptivePrivacyEngine


@dataclass(frozen=True, slots=True)
class FinalValidationReport:
    valid: bool
    issue_codes: tuple[str, ...]
    records: int
    clusters: int
    privacy_decisions: int


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    records: int
    linkage_decisions: int
    clusters: int
    privacy_decisions: int
    elapsed_seconds: float
    peak_memory_bytes: int


def validate_member3_state(
    records: Sequence[PatientRecord],
    clusters: Sequence[PatientCluster],
    privacy_decisions: Sequence[PrivacyDecision],
) -> FinalValidationReport:
    """Validate linkage/privacy invariants using safe issue codes only."""

    issues: set[str] = set()
    records_by_ref = {record.record_ref: record for record in records}
    if len(records_by_ref) != len(records):
        issues.add("DUPLICATE_RECORD_REF")

    membership_counts: dict[str, int] = {record_ref: 0 for record_ref in records_by_ref}
    pseudonym_clusters: dict[str, int] = {}
    for cluster in clusters:
        if cluster.resolution_status == ResolutionStatus.RESOLVED:
            if cluster.pseudonym_id is None:
                issues.add("RESOLVED_CLUSTER_WITHOUT_PSEUDONYM")
            else:
                pseudonym_clusters[cluster.pseudonym_id] = (
                    pseudonym_clusters.get(cluster.pseudonym_id, 0) + 1
                )
        elif cluster.pseudonym_id is not None:
            issues.add("UNSAFE_PSEUDONYM_ON_UNRESOLVED_CLUSTER")

        for record_ref in cluster.member_record_refs:
            if record_ref not in records_by_ref:
                issues.add("UNKNOWN_CLUSTER_MEMBER")
                continue
            membership_counts[record_ref] += 1
            record = records_by_ref[record_ref]
            if record.cluster_ref != cluster.cluster_ref:
                issues.add("RECORD_CLUSTER_REF_MISMATCH")
            if record.pseudonym_id != cluster.pseudonym_id:
                issues.add("PSEUDONYM_INCONSISTENCY")

    if any(count == 0 for count in membership_counts.values()):
        issues.add("RECORD_WITHOUT_CLUSTER")
    if any(count > 1 for count in membership_counts.values()):
        issues.add("RECORD_IN_MULTIPLE_CLUSTERS")
    if any(count > 1 for count in pseudonym_clusters.values()):
        issues.add("PSEUDONYM_REUSED_ACROSS_CLUSTERS")

    clinical_spans: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for record in records:
        for span in record.detections:
            if span.role == SpanRole.CLINICAL_PROTECTED:
                clinical_spans.setdefault((record.record_ref, span.field_path), []).append(
                    (span.start, span.end)
                )
    for decision in privacy_decisions:
        if decision.record_ref not in records_by_ref:
            issues.add("DECISION_FOR_UNKNOWN_RECORD")
            continue
        if decision.start is None or decision.end is None:
            continue
        for clinical_start, clinical_end in clinical_spans.get(
            (decision.record_ref, decision.field_path), []
        ):
            if decision.start < clinical_end and clinical_start < decision.end:
                issues.add("CLINICAL_SPAN_OVERLAP")

    return FinalValidationReport(
        valid=not issues,
        issue_codes=tuple(sorted(issues)),
        records=len(records),
        clusters=len(clusters),
        privacy_decisions=len(privacy_decisions),
    )


def benchmark_member3_pipeline(
    records: Sequence[PatientRecord], secret_key: bytes
) -> PerformanceMetrics:
    """Measure linkage and privacy processing without disk or network access."""

    started_tracing = not tracemalloc.is_tracing()
    if started_tracing:
        tracemalloc.start()
    started_at = time.perf_counter()
    decisions, clusters = ConservativeLinkageEngine().link_records(records)
    privacy_decisions = AdaptivePrivacyEngine().transform(
        records, clusters, secret_key
    )
    elapsed_seconds = time.perf_counter() - started_at
    _, peak_memory_bytes = tracemalloc.get_traced_memory()
    if started_tracing:
        tracemalloc.stop()
    return PerformanceMetrics(
        records=len(records),
        linkage_decisions=len(decisions),
        clusters=len(clusters),
        privacy_decisions=len(privacy_decisions),
        elapsed_seconds=elapsed_seconds,
        peak_memory_bytes=peak_memory_bytes,
    )
