# Purpose: End-to-end M2->M3->M1 integration checks and quantitative multilingual Precision/Recall/F1 benchmarks.
"""End-to-end integration tests with M3 & M1 span application plus evaluation metrics."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import tracemalloc
import unittest

from src.clinical import ClinicalIntegrityGuard
from src.contracts import FieldNode, PatientRecord, SpanRole
from src.detection import MultilingualPIIDetector
from src.linkage.engine import ConservativeLinkageEngine
from src.privacy import AdaptivePrivacyEngine
from src.pipeline import RakshaPipeline
from src.security.validation import validate_member3_state
from src.serialization.span_applier import apply_decisions_to_field


class EndToEndAndMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = ClinicalIntegrityGuard()
        self.detector = MultilingualPIIDetector(self.guard)

    def _run_m2(self, rec: PatientRecord) -> None:
        raw = self.detector.analyze_record(rec)
        spans, clinical = self.guard.protect_clinical(rec, raw)
        rec.detections = spans
        rec.clinical_attributes = clinical

    def test_cross_script_records_link_with_m3_and_apply_decisions_safely(self) -> None:
        rec_en = PatientRecord(
            record_ref="rec_0001",
            source_ref="src_1",
            loc="row:0",
            original_structure={},
            fields=[
                FieldNode("col:0:patient_name", "Mohd. Arif", "patient_name", True),
                FieldNode("col:1:dob", "1985-04-12", "dob", True),
                FieldNode("col:2:phone", "+91 98765-43210", "phone", True),
                FieldNode("col:3:age", "41 yrs", "age", True),
                FieldNode("col:4:notes", "C/O fever, Ramipril 5 mg, Dr. Sharma", "notes", True),
            ],
        )
        rec_hi = PatientRecord(
            record_ref="rec_0002",
            source_ref="src_2",
            loc="doc",
            original_structure="",
            fields=[
                FieldNode(
                    "doc",
                    "मरीज: मोहम्मद आरिफ, DOB: 12/04/1985, फोन: ९८७६५४३२१०, Dolo 650 BD x 5 days, Dr. शर्मा",
                    "doc",
                    False,
                    "narrative",
                )
            ],
        )
        rec_other = PatientRecord(
            record_ref="rec_0003",
            source_ref="src_3",
            loc="row:0",
            original_structure={},
            fields=[
                FieldNode("col:0:patient_name", "Ramesh Sharma", "patient_name", True),
                FieldNode("col:1:dob", "1979-09-20", "dob", True),
                FieldNode("col:2:phone", "9123456789", "phone", True),
                FieldNode("col:3:notes", "Parkinson's disease, BP 150/90", "notes", True),
            ],
        )

        for rec in (rec_en, rec_hi, rec_other):
            self._run_m2(rec)

        _, clusters = ConservativeLinkageEngine().link_records([rec_en, rec_hi, rec_other])
        privacy_decisions = AdaptivePrivacyEngine().transform(
            [rec_en, rec_hi, rec_other], clusters, b"synthetic-test-secret"
        )
        for rec in (rec_en, rec_hi, rec_other):
            rec.privacy_decisions = [d for d in privacy_decisions if d.record_ref == rec.record_ref]

        report = validate_member3_state([rec_en, rec_hi, rec_other], clusters, privacy_decisions)
        self.assertTrue(report.valid, msg=f"M3 validation failed: {report.issue_codes}")

        # Same patient across EN CSV & Hindi TXT must share the same PSN-..., distinct from Ramesh Sharma!
        self.assertIsNotNone(rec_en.pseudonym_id)
        self.assertEqual(rec_en.pseudonym_id, rec_hi.pseudonym_id)
        self.assertIsNotNone(rec_other.pseudonym_id)
        self.assertNotEqual(rec_en.pseudonym_id, rec_other.pseudonym_id)

        # Verify M1 span_applier preserves all clinical terms & clinician names with zero blocked clinical mutations.
        out_en_notes, blocked_en = apply_decisions_to_field(rec_en.fields[4].raw_value, rec_en, "col:4:notes")
        self.assertEqual(blocked_en, 0)
        self.assertIn("Ramipril 5 mg", out_en_notes)
        self.assertIn("C/O fever", out_en_notes)
        self.assertIn("Dr. Sharma", out_en_notes)

        out_hi_doc, blocked_hi = apply_decisions_to_field(rec_hi.fields[0].raw_value, rec_hi, "doc")
        self.assertEqual(blocked_hi, 0)
        self.assertIn("Dolo 650 BD x 5 days", out_hi_doc)
        self.assertIn("Dr. शर्मा", out_hi_doc)
        self.assertNotIn("मोहम्मद आरिफ", out_hi_doc)
        self.assertIn(rec_hi.pseudonym_id, out_hi_doc)

    def test_default_pipeline_runs_real_stages_without_test_stubs(self) -> None:
        """The public CLI pipeline must compose M1, M2, and M3 implementations."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir()
            (input_dir / "patient.csv").write_text(
                "patient_name,phone,dob,abha,notes\n"
                "Aarav Sen,9876543210,1990-05-12,12-3456-7890-1234,Dolo 650 BD x 5 days\n",
                encoding="utf-8",
            )

            previous_secret = os.environ.get("RAKSHA_SECRET")
            os.environ["RAKSHA_SECRET"] = "synthetic-pipeline-test-secret"
            try:
                metrics = RakshaPipeline().run(input_dir, output_dir)
            finally:
                if previous_secret is None:
                    os.environ.pop("RAKSHA_SECRET", None)
                else:
                    os.environ["RAKSHA_SECRET"] = previous_secret

            sanitized = (output_dir / "sanitized" / "patient.csv").read_text(
                encoding="utf-8"
            )
            records = [
                json.loads(line)
                for line in (output_dir / "records.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
                if line.strip()
            ]

            self.assertEqual(metrics.records_processed, 1)
            self.assertEqual(metrics.records_linked, 1)
            self.assertEqual(len(records), 1)
            self.assertTrue(records[0]["patient"].startswith("PSN-"))
            self.assertIn(records[0]["patient"], sanitized)
            self.assertNotIn("Aarav Sen", sanitized)
            self.assertNotIn("9876543210", sanitized)
            self.assertNotIn("12-3456-7890-1234", sanitized)
            self.assertIn("Dolo 650 BD x 5 days", sanitized)

    def test_synthetic_multilingual_benchmark_metrics(self) -> None:
        # Synthetic labeled evaluation corpus across EN, HI, and Hinglish.
        gold_cases = [
            (
                "en",
                "Patient: Ananya Deshmukh, Ph: +91 98230-11223, DOB: 1991-06-14, Dolo 650 BD, Dr. Mehta.",
                {("Ananya Deshmukh", "DIRECT_PII"), ("+91 98230-11223", "DIRECT_PII"), ("1991-06-14", "QUASI_IDENTIFIER"), ("Dr. Mehta", "STAFF_OR_FACILITY")},
                {"Dolo 650 BD"},
            ),
            (
                "hi",
                "मरीज: राजेश तिवारी, फोन: ९८१११२२२३३, जन्म तिथि: 10/08/1978, बुखार, Dr. वर्मा।",
                {("राजेश तिवारी", "DIRECT_PII"), ("९८१११२२२३३", "DIRECT_PII"), ("10/08/1978", "QUASI_IDENTIFIER"), ("Dr. वर्मा", "STAFF_OR_FACILITY")},
                {"बुखार"},
            ),
            (
                "hinglish",
                "Patient: Farhan Qureshi, C/O Imtiaz Qureshi, c/o bukhar, HbA1c 7.4%, UHID: HOSP-5521.",
                {("Farhan Qureshi", "DIRECT_PII"), ("Imtiaz Qureshi", "DIRECT_PII"), ("HOSP-5521", "DIRECT_PII")},
                {"c/o bukhar", "HbA1c 7.4%"},
            ),
        ]

        tracemalloc.start()
        t0 = time.perf_counter()

        tp = fp = fn = 0
        clinical_total = clinical_preserved = 0
        per_lang_tp: dict[str, int] = {"en": 0, "hi": 0, "hinglish": 0}
        per_lang_gold: dict[str, int] = {"en": 0, "hi": 0, "hinglish": 0}

        for idx, (lang, text, gold_pii, gold_clinical) in enumerate(gold_cases):
            rec = PatientRecord(
                record_ref=f"bench_{idx}",
                source_ref="bench_src",
                loc="doc",
                original_structure=text,
                fields=[FieldNode("doc", text, "doc", False, "narrative")],
            )
            self._run_m2(rec)

            pred_pii = {(text[s.start : s.end], s.role.name) for s in rec.detections if s.role != SpanRole.CLINICAL_PROTECTED}
            matched = len(pred_pii & gold_pii)
            tp += matched
            fp += len(pred_pii - gold_pii)
            fn += len(gold_pii - pred_pii)
            per_lang_tp[lang] += matched
            per_lang_gold[lang] += len(gold_pii)

            clinical_total += len(gold_clinical)
            for term in gold_clinical:
                if any(term in c for c in rec.clinical_attributes):
                    clinical_preserved += 1

        elapsed = time.perf_counter() - t0
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        self.assertGreaterEqual(precision, 0.90)
        self.assertGreaterEqual(recall, 0.90)
        self.assertGreaterEqual(f1, 0.90)
        self.assertEqual(clinical_preserved, clinical_total)
        self.assertLess(elapsed, 2.0)
        self.assertLess(peak_bytes, 50 * 1024 * 1024)

    def test_adversarial_co_doctor_and_distinct_similar_names_not_merged(self) -> None:
        rec_a = PatientRecord(
            record_ref="rec_a",
            source_ref="src_a",
            loc="row:0",
            original_structure={},
            fields=[
                FieldNode("col:0:patient_name", "Ramesh Kumar", "patient_name", True),
                FieldNode("col:1:dob", "1980-01-10", "dob", True),
                FieldNode("col:2:notes", "C/O Dr. Sharma, C/O fever, Wt 68 kg, TLC 11,200/cumm", "notes", True),
            ],
        )
        rec_b = PatientRecord(
            record_ref="rec_b",
            source_ref="src_b",
            loc="row:0",
            original_structure={},
            fields=[
                FieldNode("col:0:patient_name", "Ramesh Sharma", "patient_name", True),
                FieldNode("col:1:dob", "1980-01-10", "dob", True),
            ],
        )
        self._run_m2(rec_a)
        self._run_m2(rec_b)

        # C/O Dr. Sharma must NOT pollute relative_name_keys with "sharma".
        self.assertEqual(rec_a.extracted_patient_attributes.get("relative_name_keys", []), [])
        self.assertTrue(any(s.category == "CLINICIAN_NAME" and s.role == SpanRole.STAFF_OR_FACILITY for s in rec_a.detections))

        # Distinct patients with similar names must NOT be merged by M3!
        _, clusters = ConservativeLinkageEngine().link_records([rec_a, rec_b])
        self.assertEqual(len(clusters), 2)

    def test_one_thousand_multilingual_records_scale_and_memory(self) -> None:
        records = [
            PatientRecord(
                record_ref=f"scale_{i:04d}",
                source_ref="scale_src",
                loc=f"row:{i}",
                original_structure={},
                fields=[
                    FieldNode("col:0:patient_name", f"मरीज {i} आरिफ", "patient_name", True),
                    FieldNode("col:1:phone", f"98765{i % 100000:05d}", "phone", True),
                    FieldNode("col:2:notes", "C/O fever, Dolo 650 BD x 5 days, BP 120/80", "notes", True),
                ],
            )
            for i in range(1000)
        ]

        tracemalloc.start()
        t0 = time.perf_counter()
        for rec in records:
            self._run_m2(rec)
        elapsed = time.perf_counter() - t0
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        self.assertLess(elapsed, 15.0)
        self.assertLess(peak_bytes, 100 * 1024 * 1024)
        self.assertTrue(all("Dolo 650 BD x 5 days" in r.clinical_attributes for r in records[:10]))


if __name__ == "__main__":
    unittest.main()
