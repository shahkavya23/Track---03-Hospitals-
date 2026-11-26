"""Security regression and integrated Member 3 privacy tests."""

from __future__ import annotations

import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.contracts import DetectionSpan, FieldNode, PatientRecord, SpanRole, TransformType
from src.linkage.engine import ConservativeLinkageEngine
from src.privacy import AdaptivePrivacyEngine
from src.security.leakage import SecurityScanError, assert_no_leaks, scan_for_leaks


def _integrated_record(record_ref: str) -> PatientRecord:
    name = "Mohammad Arif"
    visit_date = "2026-03-10"
    age = "47"
    diagnosis = "dengue"
    record = PatientRecord(
        record_ref=record_ref,
        source_ref=f"source_{record_ref}",
        loc="row:0",
        original_structure={},
        fields=[
            FieldNode("name", name, "name", False),
            FieldNode("visit_date", visit_date, "visit_date", False),
            FieldNode("age", age, "age", False),
            FieldNode("diagnosis", diagnosis, "diagnosis", False),
        ],
        extracted_patient_attributes={
            "ids": ["ABHA|0001"],
            "ages": [age],
            "genders": ["M"],
            "geo_keys": ["village-a"],
            "diagnoses": [diagnosis],
            "visit_years": ["2026"],
            "districts": ["Jaipur District"],
            "states": ["Rajasthan"],
        },
    )
    record.detections = [
        DetectionSpan(record_ref, "name", 0, len(name), "PATIENT_NAME", SpanRole.DIRECT_PII, 1.0, "synthetic"),
        DetectionSpan(record_ref, "visit_date", 0, len(visit_date), "VISIT_DATE", SpanRole.QUASI_IDENTIFIER, 1.0, "synthetic"),
        DetectionSpan(record_ref, "age", 0, len(age), "AGE", SpanRole.QUASI_IDENTIFIER, 1.0, "synthetic"),
        DetectionSpan(record_ref, "diagnosis", 0, len(diagnosis), "DIAGNOSIS", SpanRole.CLINICAL_PROTECTED, 1.0, "synthetic"),
    ]
    return record


class LeakageScannerTests(unittest.TestCase):
    def test_clean_output_passes_recursive_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "nested").mkdir()
            (root / "nested" / "safe.txt").write_text("PSN-SAFE", encoding="utf-8")

            result = scan_for_leaks(root, ["CANARY-123", "secret-alpha"])

            self.assertEqual(result.total_findings, 0)
            self.assertEqual(result.files_scanned, 1)

    def test_content_and_filename_canaries_are_detected_without_echo(self) -> None:
        canary = "CANARY-123"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / f"patient-{canary}.txt").write_text(
                f"hidden {canary}", encoding="utf-8"
            )

            result = scan_for_leaks(root, [canary])

            self.assertGreaterEqual(result.filename_findings, 1)
            self.assertEqual(result.content_findings, 1)
            with self.assertRaises(SecurityScanError) as context:
                assert_no_leaks(root, [canary])
            self.assertNotIn(canary, str(context.exception))


class OfflinePrivacyIntegrationTests(unittest.TestCase):
    def test_linkage_and_privacy_run_without_network_and_preserve_clinical_data(self) -> None:
        records = [_integrated_record("rec_1"), _integrated_record("rec_2")]

        with patch.object(socket, "socket", side_effect=AssertionError("network blocked")):
            decisions, clusters = ConservativeLinkageEngine().link_records(records)
            privacy_decisions = AdaptivePrivacyEngine().transform(
                records, clusters, b"secret-alpha"
            )

        self.assertEqual(len(decisions), 1)
        self.assertEqual(records[0].pseudonym_id, records[1].pseudonym_id)
        transform_types = {item.transform_type for item in privacy_decisions}
        self.assertIn(TransformType.PSEUDONYMIZE, transform_types)
        self.assertIn(TransformType.DATE_SHIFT, transform_types)
        self.assertIn(TransformType.GENERALIZE, transform_types)
        self.assertFalse(any(item.field_path == "diagnosis" for item in privacy_decisions))
        self.assertNotIn("ABHA|0001", repr(privacy_decisions))
        self.assertNotIn("secret-alpha", repr(privacy_decisions))


if __name__ == "__main__":
    unittest.main()
