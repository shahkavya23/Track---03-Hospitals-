# Purpose: Tests for Verhoeff Aadhaar, ABHA, PAN, UHID/MRN, Phone, Email, PIN, Dates, and structured fields/headers/FHIR.
"""Tests for regex detectors and structured CSV/TSV/JSON/FHIR field analysis."""

from __future__ import annotations

import base64
import importlib.util
import unittest

from src.clinical import ClinicalIntegrityGuard
from src.contracts import FieldNode, PatientRecord, SpanRole
from src.detection import MultilingualPIIDetector, verhoeff_check

HAS_YAML = importlib.util.find_spec("yaml") is not None


def _valid_aadhaar_from_11(prefix11: str) -> str:
    for d in "0123456789":
        cand = prefix11 + d
        if verhoeff_check(cand):
            return cand
    raise AssertionError("No valid Verhoeff check digit found")


class RegexAndStructuredTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = ClinicalIntegrityGuard()
        self.detector = MultilingualPIIDetector(self.guard)

    def _run(self, record: PatientRecord):
        raw_spans = self.detector.analyze_record(record)
        final_spans, clinical = self.guard.protect_clinical(record, raw_spans)
        record.detections = final_spans
        record.clinical_attributes = clinical
        return final_spans

    def test_verhoeff_aadhaar_abha_pan_uhid_email_phone(self) -> None:
        valid_aadhaar = _valid_aadhaar_from_11("49911866524")
        formatted_aadhaar = f"{valid_aadhaar[:4]} {valid_aadhaar[4:8]} {valid_aadhaar[8:]}"
        invalid_aadhaar = valid_aadhaar[:-1] + str((int(valid_aadhaar[-1]) + 1) % 10)

        text = (
            f"Aadhaar: {formatted_aadhaar}, Unlabeled: {formatted_aadhaar}, "
            f"BadNum: {invalid_aadhaar}, ABHA: 12-3456-7890-1234, "
            f"PAN: ABCDE1234F, UHID: HOSP-9981, MRN: MRN-4421, "
            f"Email: patient.test@example.org, Ph: +91 98765-43210, "
            f"Insurance: POL-778899, PIN: 411045"
        )
        rec = PatientRecord(
            record_ref="rec_001",
            source_ref="src_001",
            loc="doc",
            original_structure=text,
            fields=[FieldNode("doc", text, "doc", False, "narrative")],
        )
        spans = self._run(rec)
        cats = {(s.category, rec.fields[0].raw_value[s.start : s.end]) for s in spans}

        self.assertIn(("AADHAAR", formatted_aadhaar), cats)
        self.assertNotIn(("AADHAAR", invalid_aadhaar), cats)
        self.assertIn(("ABHA", "12-3456-7890-1234"), cats)
        self.assertIn(("PAN", "ABCDE1234F"), cats)
        self.assertIn(("UHID", "HOSP-9981"), cats)
        self.assertIn(("MRN", "MRN-4421"), cats)
        self.assertIn(("EMAIL", "patient.test@example.org"), cats)
        self.assertIn(("PHONE", "+91 98765-43210"), cats)
        self.assertIn(("INSURANCE_ID", "POL-778899"), cats)
        self.assertIn(("PIN_CODE", "411045"), cats)

        ids = rec.extracted_patient_attributes.get("ids", [])
        self.assertIn(f"AADHAAR|{valid_aadhaar}", ids)
        self.assertIn("ABHA|12345678901234", ids)
        self.assertIn("PAN|ABCDE1234F", ids)
        self.assertIn("UHID|UNKNOWN_HOSPITAL|HOSP-9981", ids)
        self.assertIn("MRN|UNKNOWN_HOSPITAL|MRN-4421", ids)
        self.assertIn("INSURANCE|UNKNOWN_HOSPITAL|POL-778899", ids)
        self.assertIn("+919876543210", rec.extracted_patient_attributes.get("phones", []))

    def test_csv_with_unknown_columns_and_header_pii(self) -> None:
        # Matches exact FieldNode contract produced by Member 1's tabular parser.
        rec = PatientRecord(
            record_ref="rec_00000001",
            source_ref="src_csv",
            loc="row:0",
            original_structure={},
            fields=[
                FieldNode("col:0:patient_rahul_verma_id", "UHID-101", "patient_rahul_verma_id", True),
                FieldNode("col:1:x_col_1", "9876543210", "x_col_1", True),
                FieldNode("col:2:x_col_2", "rahul@example.com", "x_col_2", True),
                FieldNode("col:3:diagnosis", "Type 2 Diabetes Mellitus", "diagnosis", True),
            ],
        )
        spans = self._run(rec)

        header_spans = [s for s in spans if s.is_header_detection]
        self.assertEqual(len(header_spans), 1)
        self.assertEqual(header_spans[0].field_path, "@header:0")
        self.assertEqual(header_spans[0].role, SpanRole.DIRECT_PII)

        by_field = {s.field_path: s for s in spans if not s.is_header_detection}
        self.assertEqual(by_field["col:1:x_col_1"].category, "PHONE")
        self.assertEqual(by_field["col:2:x_col_2"].category, "EMAIL")
        self.assertEqual(by_field["col:3:diagnosis"].role, SpanRole.CLINICAL_PROTECTED)
        self.assertIn("Type 2 Diabetes Mellitus", rec.clinical_attributes)

    def test_nested_json_and_key_pii(self) -> None:
        rec = PatientRecord(
            record_ref="rec_00000001",
            source_ref="src_json",
            loc="/visits/0",
            original_structure={},
            fields=[
                FieldNode("/visits/0/patient/full_name", "Kavita Nair", "full_name", True),
                FieldNode("/visits/0/patient/age", "42 yrs", "age", True),
                FieldNode("/visits/0/patient/dob", "1984-02-15", "dob", True),
                FieldNode("/visits/0/doctor_name", "Dr. Arvind Kulkarni", "doctor_name", True),
                FieldNode("/visits/0/rahul.test@hosp.in", "secret_val", "rahul.test@hosp.in", True),
                FieldNode("/visits/0/notes", "C/O fever, Ramipril 5 mg OD", "notes", True),
                FieldNode("/facility", "City General Hospital", "facility", True),
            ],
        )
        spans = self._run(rec)

        span_map = {(s.field_path, s.category): s for s in spans}
        self.assertIn(("/visits/0/patient/full_name", "PATIENT_NAME"), span_map)
        self.assertIn(("/visits/0/doctor_name", "CLINICIAN_NAME"), span_map)
        self.assertEqual(
            span_map[("/visits/0/doctor_name", "CLINICIAN_NAME")].role,
            SpanRole.STAFF_OR_FACILITY,
        )
        # Age span must contain ONLY integer digits for M3 AdaptiveGeneralizer.
        age_span = span_map[("/visits/0/patient/age", "AGE")]
        age_field = next(f for f in rec.fields if f.field_path == "/visits/0/patient/age")
        self.assertEqual(age_field.raw_value[age_span.start : age_span.end], "42")

        # Key PII flagged with @key:
        self.assertTrue(
            any(s.is_header_detection and s.field_path == "@key:/visits/0/rahul.test@hosp.in" for s in spans)
        )

    def test_fhir_bundle_patient_practitioner_and_decoded_attachment(self) -> None:
        note_text = "Patient: Mohd. Arif\nC/O chest pain, Dolo 650 BD x 5 days\nPhone: 9876543210"
        b64_note = base64.b64encode(note_text.encode("utf-8")).decode("ascii")
        att_path = "/entry/2/resource/content/0/attachment/data@decoded_attachment"
        rec = PatientRecord(
            record_ref="rec_00000001",
            source_ref="src_fhir",
            loc="doc",
            original_structure={},
            fields=[
                FieldNode("/resourceType", "Bundle", "resourceType", True),
                FieldNode("/entry/0/resource/resourceType", "Patient", "resourceType", True),
                FieldNode("/entry/0/resource/name/0/family", "Arif", "family", True),
                FieldNode("/entry/0/resource/name/0/given/0", "Mohammad", "given", True),
                FieldNode("/entry/0/resource/birthDate", "1980-05-10", "birthDate", True),
                FieldNode("/entry/0/resource/telecom/0/value", "+91 9876543210", "value", True),
                FieldNode("/entry/1/resource/resourceType", "Practitioner", "resourceType", True),
                FieldNode("/entry/1/resource/name/0/family", "Rao", "family", True),
                FieldNode("/entry/1/resource/name/0/given/0", "Suresh", "given", True),
                FieldNode("/entry/2/resource/content/0/attachment/data", b64_note, "data", True),
                FieldNode(att_path, note_text, "attachment_data", False, "narrative"),
            ],
        )
        spans = self._run(rec)

        # Practitioner name must be STAFF_OR_FACILITY, NOT DIRECT_PII!
        prac_spans = [s for s in spans if "/entry/1/resource/name" in s.field_path]
        self.assertTrue(prac_spans)
        for ps in prac_spans:
            self.assertEqual(ps.role, SpanRole.STAFF_OR_FACILITY)

        # Patient name must be DIRECT_PII
        pat_spans = [s for s in spans if "/entry/0/resource/name" in s.field_path]
        self.assertTrue(pat_spans)
        for ps in pat_spans:
            self.assertEqual(ps.role, SpanRole.DIRECT_PII)

        # Decoded attachment PII + clinical preservation
        att_spans = [s for s in spans if s.field_path == att_path]
        self.assertTrue(any(s.category == "PATIENT_NAME" and note_text[s.start:s.end] == "Mohd. Arif" for s in att_spans))
        self.assertTrue(any(s.category == "PHONE" and note_text[s.start:s.end] == "9876543210" for s in att_spans))
        self.assertTrue(any(s.role == SpanRole.CLINICAL_PROTECTED and "Dolo 650" in note_text[s.start:s.end] for s in att_spans))
        self.assertIn("Dolo 650 BD x 5 days", rec.clinical_attributes)

    @unittest.skipUnless(HAS_YAML, "PyYAML not installed in current interpreter")
    def test_live_m1_parsers_roundtrip_into_detector(self) -> None:
        from src.contracts import FileFormat
        from src.ingestion.parsers import parse_tabular_document

        csv_text = "patient_name,notes\nMohammad Arif,Ramipril 5 mg and BP 150/90\n"
        records = parse_tabular_document(csv_text, "src_live", FileFormat.CSV, lambda: "rec_live_1")
        spans = self._run(records[0])
        self.assertTrue(any(s.category == "PATIENT_NAME" for s in spans))
        self.assertIn("Ramipril 5 mg", records[0].clinical_attributes)
        self.assertIn("BP 150/90", records[0].clinical_attributes)


if __name__ == "__main__":
    unittest.main()
