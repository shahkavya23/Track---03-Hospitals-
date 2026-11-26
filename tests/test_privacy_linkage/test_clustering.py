"""Synthetic tests for constraint-aware patient clustering."""

from __future__ import annotations

import unittest

from src.contracts import (
    LinkageDecision,
    LinkageVerdict,
    PatientRecord,
    ResolutionStatus,
)
from src.linkage.clustering import (
    RejectedMerge,
    cluster_records,
    evaluate_clustering,
)
from src.linkage.engine import ConservativeLinkageEngine


def _record(
    record_ref: str,
    *,
    ids: list[str] | None = None,
    phones: list[str] | None = None,
    dobs: list[str] | None = None,
) -> PatientRecord:
    return PatientRecord(
        record_ref=record_ref,
        source_ref=f"source_{record_ref}",
        loc="row:0",
        original_structure={},
        extracted_patient_attributes={
            "ids": ids or [],
            "phones": phones or [],
            "dobs": dobs or [],
        },
    )


def _decision(
    left_ref: str,
    right_ref: str,
    verdict: LinkageVerdict,
    score: float,
) -> LinkageDecision:
    return LinkageDecision(
        record_ref_a=left_ref,
        record_ref_b=right_ref,
        decision=verdict,
        score=score,
    )


class ConstraintAwareClusteringTests(unittest.TestCase):
    def test_transitive_non_match_prevents_abc_over_merge(self) -> None:
        records = [_record("rec_a"), _record("rec_b"), _record("rec_c")]
        decisions = [
            _decision("rec_a", "rec_b", LinkageVerdict.MATCH, 0.9),
            _decision("rec_b", "rec_c", LinkageVerdict.MATCH, 0.8),
            _decision("rec_a", "rec_c", LinkageVerdict.NON_MATCH, -1.0),
        ]

        result = cluster_records(records, decisions)

        self.assertEqual(
            [cluster.member_record_refs for cluster in result.clusters],
            [("rec_a", "rec_b"), ("rec_c",)],
        )
        self.assertEqual(
            result.rejected_merges,
            (RejectedMerge("rec_b", "rec_c", "CANNOT_LINK"),),
        )

    def test_missing_pairwise_support_prevents_transitive_merge(self) -> None:
        records = [_record("rec_a"), _record("rec_b"), _record("rec_c")]
        decisions = [
            _decision("rec_a", "rec_b", LinkageVerdict.MATCH, 0.9),
            _decision("rec_b", "rec_c", LinkageVerdict.MATCH, 0.8),
        ]

        result = cluster_records(records, decisions)

        self.assertEqual(
            [cluster.member_record_refs for cluster in result.clusters],
            [("rec_a", "rec_b"), ("rec_c",)],
        )
        self.assertEqual(
            result.rejected_merges,
            (
                RejectedMerge(
                    "rec_b", "rec_c", "INCOMPLETE_PAIRWISE_SUPPORT"
                ),
            ),
        )

    def test_all_pairwise_matches_form_one_cluster(self) -> None:
        records = [_record("rec_a"), _record("rec_b"), _record("rec_c")]
        decisions = [
            _decision("rec_a", "rec_b", LinkageVerdict.MATCH, 0.9),
            _decision("rec_b", "rec_c", LinkageVerdict.MATCH, 0.8),
            _decision("rec_a", "rec_c", LinkageVerdict.MATCH, 0.7),
        ]

        result = cluster_records(records, decisions)

        self.assertEqual(len(result.clusters), 1)
        self.assertEqual(
            result.clusters[0].member_record_refs,
            ("rec_a", "rec_b", "rec_c"),
        )
        self.assertEqual(
            result.clusters[0].resolution_status,
            ResolutionStatus.RESOLVED,
        )
        self.assertEqual(result.rejected_merges, ())

    def test_abstain_never_merges_records(self) -> None:
        records = [_record("rec_a"), _record("rec_b")]
        decisions = [
            _decision("rec_a", "rec_b", LinkageVerdict.ABSTAIN, 0.6)
        ]

        result = cluster_records(records, decisions)

        self.assertEqual(
            [cluster.member_record_refs for cluster in result.clusters],
            [("rec_a",), ("rec_b",)],
        )

    def test_conflicting_duplicate_decisions_fail_closed(self) -> None:
        records = [_record("rec_a"), _record("rec_b")]
        decisions = [
            _decision("rec_a", "rec_b", LinkageVerdict.MATCH, 0.9),
            _decision("rec_a", "rec_b", LinkageVerdict.NON_MATCH, -1.0),
        ]

        result = cluster_records(records, decisions)

        self.assertEqual(
            [cluster.member_record_refs for cluster in result.clusters],
            [("rec_a",), ("rec_b",)],
        )


class ClusterStatusAndDeterminismTests(unittest.TestCase):
    def test_singleton_status_uses_stable_identity_evidence(self) -> None:
        records = [
            _record("rec_conflict", ids=["ABHA|1", "ABHA|2"]),
            _record("rec_resolved", ids=["ABHA|3"]),
            _record("rec_weak"),
        ]

        result = cluster_records(records, [])
        status_by_member = {
            cluster.member_record_refs[0]: cluster.resolution_status
            for cluster in result.clusters
        }

        self.assertEqual(
            status_by_member,
            {
                "rec_conflict": ResolutionStatus.CONFLICT,
                "rec_resolved": ResolutionStatus.RESOLVED,
                "rec_weak": ResolutionStatus.UNRESOLVED,
            },
        )

    def test_cluster_ids_do_not_depend_on_input_order(self) -> None:
        forward_records = [_record("rec_a"), _record("rec_b"), _record("rec_c")]
        reversed_records = list(
            reversed([_record("rec_a"), _record("rec_b"), _record("rec_c")])
        )
        decisions = [
            _decision("rec_a", "rec_b", LinkageVerdict.MATCH, 0.9),
            _decision("rec_a", "rec_c", LinkageVerdict.NON_MATCH, -1.0),
            _decision("rec_b", "rec_c", LinkageVerdict.MATCH, 0.8),
        ]

        forward = cluster_records(forward_records, decisions)
        reversed_result = cluster_records(reversed_records, list(reversed(decisions)))

        forward_view = [
            (cluster.cluster_ref, cluster.member_record_refs)
            for cluster in forward.clusters
        ]
        reversed_view = [
            (cluster.cluster_ref, cluster.member_record_refs)
            for cluster in reversed_result.clusters
        ]
        self.assertEqual(forward_view, reversed_view)


class ClusteringMetricsAndIntegrationTests(unittest.TestCase):
    def test_cluster_quality_metrics_use_synthetic_truth(self) -> None:
        records = [_record("rec_a"), _record("rec_b"), _record("rec_c")]
        result = cluster_records(
            records,
            [_decision("rec_a", "rec_b", LinkageVerdict.MATCH, 0.9)],
        )

        metrics = evaluate_clustering(
            result,
            {
                "rec_a": "patient_1",
                "rec_b": "patient_1",
                "rec_c": "patient_2",
            },
        )

        self.assertEqual(metrics.pairwise_precision, 1.0)
        self.assertEqual(metrics.pairwise_recall, 1.0)
        self.assertEqual(metrics.false_merge_rate, 0.0)
        self.assertEqual(metrics.false_split_rate, 0.0)
        self.assertEqual(metrics.cluster_consistency, 1.0)

    def test_integrated_engine_blocks_matches_and_clusters(self) -> None:
        records = [
            _record("rec_a", ids=["ABHA|0001"]),
            _record("rec_b", ids=["ABHA|0001"]),
            _record("rec_c"),
        ]

        decisions, clusters = ConservativeLinkageEngine().link_records(records)

        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].decision, LinkageVerdict.MATCH)
        self.assertEqual(
            [cluster.member_record_refs for cluster in clusters],
            [("rec_a", "rec_b"), ("rec_c",)],
        )
        self.assertEqual(records[0].cluster_ref, records[1].cluster_ref)
        self.assertNotEqual(records[0].cluster_ref, records[2].cluster_ref)


if __name__ == "__main__":
    unittest.main()
