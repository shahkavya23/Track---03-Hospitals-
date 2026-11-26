# Purpose: Adversarial robustness tests using unseen names, INN drugs, lab units, morphological diagnoses, and unseen column headers.
"""Robustness tests verifying general logic rather than hardcoded sample lists."""

from __future__ import annotations

import unittest

from src.clinical import ClinicalIntegrityGuard
from src.contracts import FieldNode, PatientRecord, SpanRole
from src.detection import MultilingualPIIDetector


class RobustUnseenDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = ClinicalIntegrityGuard()
        self.detector = MultilingualPIIDetector(self.guard)

    def _run(self, record: PatientRecord) -> list:
        raw = self.detector.analyze_record(record)
        spans, clinical = self.guard.protect_clinical(record, raw)
        record.detections = spans
        record.clinical_attributes = clinical
        return spans

    def test_unseen_inn_drugs_morphological_diagnoses_eponyms_and_labs(self) -> None:
        # None of these specific drug/lab/eponym/diagnosis names appear in any small sample fixture!
        note = (
            "Pt presented with C/O severe epigastric pain radiating to back, "
            "C/O hematuria x 2 days, C/O pedal edema. "
            "Dx: Takayasu arteritis, Cholecystitis, Hepatomegaly, Thrombocytopenia. "
            "Labs: Serum Procalcitonin 4.2 ng/mL, Alkaline Phosphatase 210 U/L, NT-proBNP 950 pg/mL. "
            "Rx: Tab. Vortioxetine 10 mg OD, Rosuvastatin 20 mg HS, Cefoperazone 1 g IV BD, "
            "Undergone Percutaneous Nephrolithotomy."
        )
        rec = PatientRecord(
            record_ref="rec_unseen_clin",
            source_ref="src_u1",
            loc="doc",
            original_structure=note,
            fields=[FieldNode("doc", note, "doc", False, "narrative")],
        )
        spans = self._run(rec)

        non_clinical = [s for s in spans if s.role != SpanRole.CLINICAL_PROTECTED]
        self.assertEqual(non_clinical, [], msg=f"False PII in unseen clinical note: {[(note[s.start:s.end], s.category) for s in non_clinical]}")

        joined = " | ".join(rec.clinical_attributes)
        for must_keep in (
            "epigastric pain",
            "hematuria",
            "pedal edema",
            "Takayasu arteritis",
            "Cholecystitis",
            "Hepatomegaly",
            "Thrombocytopenia",
            "Procalcitonin 4.2 ng/mL",
            "Alkaline Phosphatase 210 U/L",
            "NT-proBNP 950 pg/mL",
            "Tab. Vortioxetine 10 mg OD",
            "Rosuvastatin 20 mg HS",
            "Cefoperazone 1 g IV BD",
            "Nephrolithotomy",
        ):
            self.assertIn(must_keep, joined)

    def test_unseen_camel_case_and_abbreviated_column_headers(self) -> None:
        rec = PatientRecord(
            record_ref="rec_unseen_cols",
            source_ref="src_u2",
            loc="row:0",
            original_structure={},
            fields=[
                FieldNode("col:0:ptFullNm", "Devika Subramanian", "ptFullNm", True),
                FieldNode("col:1:altMobNum", "+91-94440-12345", "altMobNum", True),
                FieldNode("col:2:ptDob", "1977-11-03", "ptDob", True),
                FieldNode("col:3:refByDr", "Dr. Karthik Balaji", "refByDr", True),
                FieldNode("col:4:currAddr", "Flat 12B, Kaveri Enclave, Sector 9, Noida 201301", "currAddr", True),
                FieldNode("col:5:mrNo", "MR-88412", "mrNo", True),
                FieldNode("col:6:primaryDx", "Acute Pancreatitis", "primaryDx", True),
                FieldNode("col:7:dischargeMeds", "Cap. Esomeprazole 40 mg OD", "dischargeMeds", True),
            ],
        )
        spans = self._run(rec)
        by_path = {s.field_path: s for s in spans if not s.is_header_detection}

        self.assertEqual(by_path["col:0:ptFullNm"].category, "PATIENT_NAME")
        self.assertEqual(by_path["col:1:altMobNum"].category, "PHONE")
        self.assertEqual(by_path["col:2:ptDob"].category, "DOB")
        self.assertEqual(by_path["col:3:refByDr"].role, SpanRole.STAFF_OR_FACILITY)
        self.assertEqual(by_path["col:4:currAddr"].category, "ADDRESS")
        self.assertEqual(by_path["col:5:mrNo"].category, "MRN")
        self.assertEqual(by_path["col:6:primaryDx"].role, SpanRole.CLINICAL_PROTECTED)
        self.assertEqual(by_path["col:7:dischargeMeds"].role, SpanRole.CLINICAL_PROTECTED)

    def test_unlabeled_demographic_lines_unprefixed_addresses_and_single_digit_dates(self) -> None:
        text = (
            "Anil Kapoor, 52/M, 42 Shanti Vihar, Jaipur 302015, Regn. No. CR-7721. "
            "Admitted on 5/4/2024 with C/O dry cough and fever. "
            "सुनील वर्मा को चक्कर और कमजोरी की शिकायत है। "
            "Referring Doctor: Dr. Nandini Iyer."
        )
        rec = PatientRecord(
            record_ref="rec_unseen_free",
            source_ref="src_u3",
            loc="doc",
            original_structure=text,
            fields=[FieldNode("doc", text, "doc", False, "narrative")],
        )
        spans = self._run(rec)
        extracted = {(text[s.start : s.end], s.category, s.role) for s in spans}

        self.assertIn(("Anil Kapoor", "PATIENT_NAME", SpanRole.DIRECT_PII), extracted)
        self.assertIn(("52", "AGE", SpanRole.QUASI_IDENTIFIER), extracted)
        self.assertIn(("CR-7721", "UHID", SpanRole.DIRECT_PII), extracted)
        self.assertIn(("Dr. Nandini Iyer", "CLINICIAN_NAME", SpanRole.STAFF_OR_FACILITY), extracted)
        self.assertTrue(any(cat == "ADDRESS" and "Shanti Vihar" in sl for sl, cat, _ in extracted))
        self.assertTrue(any("5/4/2024" == sl and role == SpanRole.QUASI_IDENTIFIER for sl, _, role in extracted))
        self.assertTrue(any("C/O dry cough" in c for c in rec.clinical_attributes))
        self.assertTrue(any("चक्कर" in c for c in rec.clinical_attributes))
        self.assertTrue(any("कमजोरी" in c for c in rec.clinical_attributes))


if __name__ == "__main__":
    unittest.main()
