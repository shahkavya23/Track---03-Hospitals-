# Purpose: Clinical preservation, precedence, and anti-concealment tests for Member 2.
"""Tests for clinical preservation, precedence, and anti-concealment invariants."""

from __future__ import annotations

import unittest

from src.clinical import ClinicalIntegrityGuard
from src.contracts import DetectionSpan, FieldNode, PatientRecord, SpanRole
from src.detection import MultilingualPIIDetector


class ClinicalPreservationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = ClinicalIntegrityGuard()
        self.detector = MultilingualPIIDetector(self.guard)

    def test_medications_dosages_vitals_labs_diagnoses_and_procedures_preserved(self) -> None:
        note = (
            "Dx: Parkinson's disease, Type 2 Diabetes Mellitus. "
            "Vitals: BP 150/90 mmHg, SpO2 98%, HR 78 bpm, Temp 101.2 F. "
            "Labs: HbA1c 7.4%, Creatinine 1.3 mg/dL, TLC 11,200/cumm. "
            "Rx: Ramipril 5 mg OD, Dolo 650 BD x 5 days, 1-0-1. "
            "Procedure: CABG done."
        )
        rec = PatientRecord(
            record_ref="rec_clin_1",
            source_ref="src_clin_1",
            loc="doc",
            original_structure=note,
            fields=[FieldNode("doc", note, "doc", False, "narrative")],
        )
        raw_spans = self.detector.analyze_record(rec)
        final_spans, clinical_attrs = self.guard.protect_clinical(rec, raw_spans)

        # Zero false PII detections inside clinical-only note!
        non_clinical = [s for s in final_spans if s.role != SpanRole.CLINICAL_PROTECTED]
        self.assertEqual(non_clinical, [], msg=f"Unexpected non-clinical spans: {non_clinical}")

        joined = " | ".join(clinical_attrs)
        for required in (
            "Parkinson's disease",
            "Type 2 Diabetes Mellitus",
            "BP 150/90 mmHg",
            "SpO2 98%",
            "HR 78 bpm",
            "Temp 101.2 F",
            "HbA1c 7.4%",
            "Creatinine 1.3 mg/dL",
            "TLC 11,200/cumm",
            "Ramipril 5 mg OD",
            "Dolo 650 BD x 5 days",
            "1-0-1",
            "CABG",
        ):
            self.assertIn(required, joined)

    def test_clinical_precedence_overrides_erroneous_incoming_ner_guesses(self) -> None:
        note = "Parkinson's disease treated with Dolo 650 1-0-1"
        rec = PatientRecord(
            record_ref="rec_clin_2",
            source_ref="src_clin_2",
            loc="doc",
            original_structure=note,
            fields=[FieldNode("doc", note, "doc", False, "narrative")],
        )
        # Simulate noisy NER tagging "Parkinson" as PERSON_NAME and "1-0-1" as DATE.
        noisy_spans = [
            DetectionSpan("rec_clin_2", "doc", 0, 9, "PERSON_NAME", SpanRole.DIRECT_PII, 0.70, "noisy_ner"),
            DetectionSpan("rec_clin_2", "doc", 43, 48, "DATE", SpanRole.QUASI_IDENTIFIER, 0.65, "noisy_date"),
        ]
        final_spans, clinical_attrs = self.guard.protect_clinical(rec, noisy_spans)

        self.assertTrue(all(s.role == SpanRole.CLINICAL_PROTECTED for s in final_spans))
        self.assertIn("Parkinson's disease", clinical_attrs)
        self.assertIn("Dolo 650 1-0-1", clinical_attrs)

    def test_clinical_field_never_conceals_embedded_hard_pii(self) -> None:
        # Even inside a `diagnosis` column, a real phone number or ABHA must NOT be hidden!
        rec = PatientRecord(
            record_ref="rec_clin_3",
            source_ref="src_clin_3",
            loc="row:0",
            original_structure={},
            fields=[
                FieldNode(
                    "col:0:diagnosis",
                    "Type 2 Diabetes Mellitus (call 9876543210, ABHA 12-3456-7890-1234)",
                    "diagnosis",
                    True,
                    "str",
                )
            ],
        )
        raw_spans = self.detector.analyze_record(rec)
        final_spans, clinical_attrs = self.guard.protect_clinical(rec, raw_spans)

        pii_cats = {s.category for s in final_spans if s.role == SpanRole.DIRECT_PII}
        self.assertIn("PHONE", pii_cats)
        self.assertIn("ABHA", pii_cats)
        # Clinical diagnosis itself still survives, and clinical_attrs does NOT contain the phone/ABHA.
        self.assertTrue(any("Type 2 Diabetes Mellitus" in c for c in clinical_attrs))
        for c in clinical_attrs:
            self.assertNotIn("9876543210", c)
            self.assertNotIn("12-3456-7890-1234", c)


if __name__ == "__main__":
    unittest.main()
