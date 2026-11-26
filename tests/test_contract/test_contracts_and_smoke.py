# Purpose: Verifies contract invariants, fail-closed RAKSHA_SECRET check, and stubbed end-to-end output schema.
"""Contract invariant tests and stubbed end-to-end smoke test (Phase 1+2)."""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
import os
import tempfile
import unittest
from pathlib import Path

from src.contracts import (
    AuditMetrics,
    DetectionSpan,
    LinkageDecision,
    PatientCluster,
    PatientRecord,
    PrivacyDecision,
    ResolutionStatus,
    SourceFile,
    SpanRole,
    TransformType,
)
from src.pipeline import RakshaPipeline


class _StubDetector:
    """Explicit test stub simulating Member 2 detection."""

    def analyze_record(self, record: PatientRecord) -> list[DetectionSpan]:
        spans: list[DetectionSpan] = []
        for node in record.fields:
            if node.header_key == "patient_name" and node.raw_value.strip():
                spans.append(
                    DetectionSpan(
                        record_ref=record.record_ref,
                        field_path=node.field_path,
                        start=0,
                        end=len(node.raw_value),
                        category="PERSON_NAME",
                        role=SpanRole.DIRECT_PII,
                        confidence=1.0,
                        detector_source="stub_detector",
                    )
                )
                record.extracted_patient_attributes.setdefault("names", []).append(node.raw_value)
            if node.header_key == "notes":
                for term in ("Ramipril 5 mg", "BP 150/90"):
                    idx = node.raw_value.find(term)
                    if idx != -1:
                        spans.append(
                            DetectionSpan(
                                record_ref=record.record_ref,
                                field_path=node.field_path,
                                start=idx,
                                end=idx + len(term),
                                category="CLINICAL",
                                role=SpanRole.CLINICAL_PROTECTED,
                                confidence=1.0,
                                detector_source="stub_clinical",
                            )
                        )
        return spans


class _StubClinicalGuard:
    """Explicit test stub simulating Member 2 clinical guard."""

    def protect_clinical(
        self, record: PatientRecord, spans: list[DetectionSpan]
    ) -> tuple[list[DetectionSpan], list[str]]:
        clinical = []
        for span in spans:
            if span.role == SpanRole.CLINICAL_PROTECTED:
                for node in record.fields:
                    if node.field_path == span.field_path:
                        clinical.append(node.raw_value[span.start : span.end])
        return list(spans), clinical


class _StubLinker:
    """Explicit test stub simulating Member 3 clustering."""

    def link_records(
        self, records: list[PatientRecord]
    ) -> tuple[list[LinkageDecision], list[PatientCluster]]:
        clusters: list[PatientCluster] = []
        for idx, rec in enumerate(records):
            names = rec.extracted_patient_attributes.get("names", [])
            if names:
                cid = f"clu_{idx}"
                rec.cluster_ref = cid
                clusters.append(
                    PatientCluster(
                        cluster_ref=cid,
                        member_record_refs=(rec.record_ref,),
                        resolution_status=ResolutionStatus.RESOLVED,
                    )
                )
            else:
                cid = f"clu_unres_{idx}"
                rec.cluster_ref = cid
                clusters.append(
                    PatientCluster(
                        cluster_ref=cid,
                        member_record_refs=(rec.record_ref,),
                        resolution_status=ResolutionStatus.UNRESOLVED,
                    )
                )
        return [], clusters


class _StubPrivacyEngine:
    """Explicit test stub simulating Member 3 keyed-HMAC pseudonymization."""

    def transform(
        self,
        records: list[PatientRecord],
        clusters: list[PatientCluster],
        secret_key: bytes,
    ) -> list[PrivacyDecision]:
        decisions: list[PrivacyDecision] = []
        cluster_map = {c.cluster_ref: c for c in clusters}
        for rec in records:
            cluster = cluster_map.get(rec.cluster_ref or "")
            if cluster and cluster.resolution_status == ResolutionStatus.RESOLVED:
                seed_name = rec.extracted_patient_attributes["names"][0].encode("utf-8")
                digest = hmac.new(secret_key, seed_name, hashlib.sha256).hexdigest()[:6].upper()
                psn = f"PSN-{digest}"
                cluster.pseudonym_id = psn
                rec.pseudonym_id = psn
                for span in rec.detections:
                    if span.role == SpanRole.DIRECT_PII:
                        decisions.append(
                            PrivacyDecision(
                                record_ref=rec.record_ref,
                                field_path=span.field_path,
                                start=span.start,
                                end=span.end,
                                transform_type=TransformType.PSEUDONYMIZE,
                                replacement_value=psn,
                            )
                        )
            else:
                rec.pseudonym_id = None
        return decisions


class ContractAndSmokeTests(unittest.TestCase):
    def test_contract_invariants(self) -> None:
        with self.assertRaises(ValueError):
            DetectionSpan("rec_1", "doc", 5, 2, "NAME", SpanRole.DIRECT_PII, 0.9, "test")
        with self.assertRaises(ValueError):
            DetectionSpan("rec_1", "doc", 0, 2, "NAME", SpanRole.DIRECT_PII, 1.5, "test")
        with self.assertRaises(ValueError):
            PatientCluster("clu_1", ("rec_1",), ResolutionStatus.UNRESOLVED, pseudonym_id="PSN-123")

    def test_pipeline_fails_closed_without_secret(self) -> None:
        old = os.environ.pop("RAKSHA_SECRET", None)
        try:
            pipeline = RakshaPipeline(
                detector=_StubDetector(),
                clinical_guard=_StubClinicalGuard(),
                linker=_StubLinker(),
                privacy_engine=_StubPrivacyEngine(),
            )
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(RuntimeError):
                    pipeline.run(Path(tmp), Path(tmp) / "out")
        finally:
            if old is not None:
                os.environ["RAKSHA_SECRET"] = old

    def test_stubbed_e2e_smoke_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            in_dir = root / "input"
            (in_dir / "registration").mkdir(parents=True)
            (in_dir / "discharge").mkdir(parents=True)

            csv_path = in_dir / "registration" / "hospital.csv"
            csv_path.write_text(
                "patient_name,notes\n"
                "Mohammad Arif,Ramipril 5 mg and BP 150/90\n"
                ",Fever observation\n",
                encoding="utf-8",
            )
            bin_path = in_dir / "discharge" / "scan.pdf"
            bin_path.write_bytes(b"%PDF-1.4 fake binary")

            def run_with_secret(secret: str, out_name: str) -> tuple[dict, list[dict], str]:
                old = os.environ.get("RAKSHA_SECRET")
                os.environ["RAKSHA_SECRET"] = secret
                try:
                    out_dir = root / out_name
                    pipeline = RakshaPipeline(
                        detector=_StubDetector(),
                        clinical_guard=_StubClinicalGuard(),
                        linker=_StubLinker(),
                        privacy_engine=_StubPrivacyEngine(),
                    )
                    pipeline.run(in_dir, out_dir)
                    report_text = (out_dir / "report.json").read_text(encoding="utf-8")
                    report = json.loads(report_text)
                    recs = [
                        json.loads(line)
                        for line in (out_dir / "records.jsonl").read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    ]
                    sanitized_csv = (out_dir / "sanitized" / "registration" / "hospital.csv").read_text(
                        encoding="utf-8"
                    )
                    self.assertFalse((out_dir / "sanitized" / "discharge" / "scan.pdf").exists())
                    self.assertNotIn("scan.pdf", report_text)
                    self.assertNotIn("Mohammad Arif", report_text)
                    self.assertNotIn("Mohammad Arif", sanitized_csv)
                    return report, recs, sanitized_csv
                finally:
                    if old is None:
                        os.environ.pop("RAKSHA_SECRET", None)
                    else:
                        os.environ["RAKSHA_SECRET"] = old

            report1, recs1, csv1 = run_with_secret("secret-alpha", "out1")
            report2, recs2, _ = run_with_secret("secret-alpha", "out2")
            _, recs3, _ = run_with_secret("secret-beta", "out3")

            self.assertEqual(report1["counts"]["files_total"], 2)
            self.assertEqual(report1["counts"]["files_sanitized"], 1)
            self.assertEqual(report1["counts"]["files_quarantined"], 1)
            self.assertEqual(report1["counts"]["records_processed"], 2)
            self.assertEqual(report1["counts"]["records_linked"], 1)
            self.assertGreater(report1["resources"]["peak_rss_mb"], 0.0)
            self.assertGreaterEqual(report1["timing"]["seconds"], 0.0)

            self.assertEqual(recs1[0]["loc"], "row:0")
            self.assertEqual(recs1[1]["loc"], "row:1")
            self.assertIsNone(recs1[1]["patient"])
            self.assertTrue(recs1[0]["patient"].startswith("PSN-"))
            self.assertIn(recs1[0]["patient"], csv1)
            self.assertIn("Ramipril 5 mg", csv1)
            self.assertIn("BP 150/90", csv1)

            # Determinism across runs and key sensitivity
            self.assertEqual(recs1, recs2)
            self.assertNotEqual(recs1[0]["patient"], recs3[0]["patient"])


if __name__ == "__main__":
    unittest.main()
