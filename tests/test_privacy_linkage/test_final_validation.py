"""Final invariants, determinism, and synthetic performance tests."""

from __future__ import annotations

import unittest

from src.contracts import (
    DetectionSpan,
    PatientCluster,
    PatientRecord,
    PrivacyDecision,
    ResolutionStatus,
    SpanRole,
    TransformType,
)
from src.linkage.engine import ConservativeLinkageEngine
from src.privacy import AdaptivePrivacyEngine
from src.security.validation import benchmark_member3_pipeline, validate_member3_state


def _record(record_ref: str, patient_number: int) -> PatientRecord:
    return PatientRecord(
        record_ref=record_ref,
        source_ref=f"source_{record_ref}",
        loc="row:0",
        original_structure={},
        extracted_patient_attributes={"ids": [f"ABHA|{patient_number:08d}"]},
    )


class FinalInvariantTests(unittest.TestCase):
    def test_valid_integrated_state_passes(self) -> None:
        records = [_record("rec_1", 1), _record("rec_2", 1)]
        _, clusters = ConservativeLinkageEngine().link_records(records)
        privacy_decisions = AdaptivePrivacyEngine().transform(
            records, clusters, b"secret-alpha"
        )

        report = validate_member3_state(records, clusters, privacy_decisions)

        self.assertTrue(report.valid)
        self.assertEqual(report.issue_codes, ())

    def test_clinical_overlap_is_rejected(self) -> None:
        record = _record("rec_1", 1)
        record.cluster_ref = "clu_1"
        record.pseudonym_id = "PSN-SAFE"
        record.detections = [
            DetectionSpan(
                "rec_1", "notes", 0, 10, "CLINICAL", SpanRole.CLINICAL_PROTECTED, 1.0, "synthetic"
            )
        ]
        cluster = PatientCluster(
            "clu_1", ("rec_1",), ResolutionStatus.RESOLVED, "PSN-SAFE"
        )
        unsafe = PrivacyDecision(
            "rec_1", "notes", 5, 8, TransformType.REDACT, "[REDACTED]"
        )

        report = validate_member3_state([record], [cluster], [unsafe])

        self.assertFalse(report.valid)
        self.assertIn("CLINICAL_SPAN_OVERLAP", report.issue_codes)

    def test_end_to_end_result_is_order_deterministic(self) -> None:
        first_records = [_record("rec_1", 1), _record("rec_2", 1), _record("rec_3", 2)]
        second_records = list(
            reversed([_record("rec_1", 1), _record("rec_2", 1), _record("rec_3", 2)])
        )

        def run(records: list[PatientRecord]) -> tuple[list, list, list]:
            decisions, clusters = ConservativeLinkageEngine().link_records(records)
            privacy = AdaptivePrivacyEngine().transform(records, clusters, b"secret-alpha")
            decision_view = [
                (item.record_ref_a, item.record_ref_b, item.decision, item.score)
                for item in decisions
            ]
            cluster_view = [
                (item.cluster_ref, item.member_record_refs, item.pseudonym_id)
                for item in clusters
            ]
            privacy_view = [
                (item.record_ref, item.field_path, item.transform_type, item.replacement_value)
                for item in privacy
            ]
            return decision_view, cluster_view, privacy_view

        self.assertEqual(run(first_records), run(second_records))


class SyntheticPerformanceTests(unittest.TestCase):
    def test_one_thousand_records_stay_within_generous_resource_bounds(self) -> None:
        records = [
            _record(f"rec_{index:04d}", index // 2)
            for index in range(1000)
        ]

        metrics = benchmark_member3_pipeline(records, b"secret-alpha")

        self.assertEqual(metrics.records, 1000)
        self.assertEqual(metrics.clusters, 500)
        self.assertLess(metrics.elapsed_seconds, 10.0)
        self.assertLess(metrics.peak_memory_bytes, 100 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
