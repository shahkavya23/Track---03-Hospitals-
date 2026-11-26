# Purpose: Tests for English, Hindi (Devanagari), and Hinglish context disambiguation, relatives, and propagation.
"""Tests for multilingual free-text detection, role disambiguation, and propagation."""

from __future__ import annotations

import unittest

from src.clinical import ClinicalIntegrityGuard
from src.contracts import FieldNode, PatientRecord, SpanRole
from src.detection import MultilingualPIIDetector


class MultilingualContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = ClinicalIntegrityGuard()
        self.detector = MultilingualPIIDetector(self.guard)

    def _analyze(self, text: str) -> tuple[PatientRecord, list]:
        rec = PatientRecord(
            record_ref="rec_txt_1",
            source_ref="src_txt_1",
            loc="doc",
            original_structure=text,
            fields=[FieldNode("doc", text, "doc", False, "narrative")],
        )
        raw_spans = self.detector.analyze_record(rec)
        spans, clinical = self.guard.protect_clinical(rec, raw_spans)
        rec.detections = spans
        rec.clinical_attributes = clinical
        return rec, spans

    def test_meaning_trap_co_care_of_vs_complaint_of_and_doctor(self) -> None:
        text = (
            "Patient: Meera, W/o Rajan, C/O Suresh. "
            "Pt presented with C/O fever x 3 days and C/O chest pain. "
            "Seen by Dr. Ramesh Sharma."
        )
        rec, spans = self._analyze(text)
        extracted = {
            (text[s.start : s.end], s.category, s.role)
            for s in spans
        }

        self.assertIn(("Meera", "PATIENT_NAME", SpanRole.DIRECT_PII), extracted)
        self.assertIn(("Rajan", "RELATIVE_NAME", SpanRole.DIRECT_PII), extracted)
        self.assertIn(("Suresh", "RELATIVE_NAME", SpanRole.DIRECT_PII), extracted)
        self.assertIn(("Dr. Ramesh Sharma", "CLINICIAN_NAME", SpanRole.STAFF_OR_FACILITY), extracted)

        # Clinical complaints must be CLINICAL_PROTECTED, NEVER PII!
        clinical_slices = [text[s.start : s.end] for s in spans if s.role == SpanRole.CLINICAL_PROTECTED]
        self.assertTrue(any("C/O fever" in c for c in clinical_slices))
        self.assertTrue(any("C/O chest pain" in c for c in clinical_slices))
        self.assertNotIn("fever", rec.extracted_patient_attributes.get("relative_name_keys", []))

    def test_relatives_so_do_wo_and_ho_history_of(self) -> None:
        text = (
            "Ravi, S/o Mahesh and Riya, D/o Suresh visited OPD. "
            "H/o Hypertension and H/o Diabetes Mellitus."
        )
        rec, spans = self._analyze(text)
        extracted = {(text[s.start : s.end], s.category, s.role) for s in spans}

        self.assertIn(("Ravi", "PATIENT_NAME", SpanRole.DIRECT_PII), extracted)
        self.assertIn(("Mahesh", "RELATIVE_NAME", SpanRole.DIRECT_PII), extracted)
        self.assertIn(("Riya", "PATIENT_NAME", SpanRole.DIRECT_PII), extracted)
        self.assertIn(("Suresh", "RELATIVE_NAME", SpanRole.DIRECT_PII), extracted)
        # H/o Hypertension must be protected clinical, not relative!
        self.assertTrue(any(s.role == SpanRole.CLINICAL_PROTECTED and "Hypertension" in text[s.start:s.end] for s in spans))

    def test_hindi_devanagari_and_hinglish_mixed_script_with_offsets(self) -> None:
        text = (
            "मरीज: मोहम्मद आरिफ, उम्र 45 वर्ष, फोन: ९८७६५४३२१०, "
            "पता: मकान नं. 14, गांधी नगर, जयपुर। "
            "Dr. शर्मा ने Dolo 650 BD और बुखार की दवा दी। "
            "Arif ji ko c/o bukhar hai."
        )
        rec, spans = self._analyze(text)

        # Verify every single span slices cleanly in original UTF-8 text.
        for s in spans:
            self.assertLess(s.start, s.end)
            self.assertLessEqual(s.end, len(text))

        slices_by_role = [(text[s.start : s.end], s.category, s.role) for s in spans]
        self.assertTrue(any("मोहम्मद आरिफ" in sl and role == SpanRole.DIRECT_PII for sl, _, role in slices_by_role))
        self.assertTrue(any(sl == "45" and cat == "AGE" for sl, cat, _ in slices_by_role))
        self.assertTrue(any(sl == "९८७६५४३२१०" and cat == "PHONE" for sl, cat, _ in slices_by_role))
        self.assertTrue(any("मकान नं. 14, गांधी नगर, जयपुर" in sl and cat == "ADDRESS" for sl, cat, _ in slices_by_role))
        self.assertTrue(any("Dr. शर्मा" in sl and role == SpanRole.STAFF_OR_FACILITY for sl, _, role in slices_by_role))
        self.assertTrue(any("Arif ji" in sl and role == SpanRole.DIRECT_PII for sl, _, role in slices_by_role))
        self.assertTrue(any("Dolo 650 BD" in sl and role == SpanRole.CLINICAL_PROTECTED for sl, _, role in slices_by_role))
        self.assertTrue(any("बुखार" in sl and role == SpanRole.CLINICAL_PROTECTED for sl, _, role in slices_by_role))
        self.assertTrue(any("c/o bukhar" in sl and role == SpanRole.CLINICAL_PROTECTED for sl, _, role in slices_by_role))

        self.assertIn("ARF_MHMD", rec.extracted_patient_attributes.get("name_keys", []))
        self.assertIn("+919876543210", rec.extracted_patient_attributes.get("phones", []))

    def test_repeated_names_and_cross_script_propagation_in_note(self) -> None:
        text = (
            "Patient: Mohammad Arif, 38/M.\n"
            "Day 1: Arif complained of cough.\n"
            "Day 2: मोहम्मद आरिफ की हालत स्थिर है। Dr. Arif reviewed ECG."
        )
        _, spans = self._analyze(text)
        pii_slices = [(s.start, text[s.start : s.end], s.role) for s in spans if s.category in {"PATIENT_NAME", "PERSON_NAME"}]
        texts = [sl for _, sl, _ in pii_slices]

        self.assertIn("Mohammad Arif", texts)
        self.assertIn("Arif", texts)
        self.assertIn("मोहम्मद आरिफ", texts)
        # "Dr. Arif" must stay CLINICIAN_NAME (STAFF_OR_FACILITY), NOT redacted as patient!
        dr_arif = [s for s in spans if "Dr. Arif" in text[s.start : s.end]]
        self.assertTrue(dr_arif)
        self.assertEqual(dr_arif[0].role, SpanRole.STAFF_OR_FACILITY)

    def test_rare_unseen_indian_names_and_unexpected_unicode(self) -> None:
        text = (
            "Patient:\u200b Thangjam\u200dchaobi Devi, W/o Kshetrimayum\u00a0Biren. "
            "Prescribed Tab. Zylomed-XR 250 mg BD x 7 days."
        )
        rec, spans = self._analyze(text)
        pii_texts = [text[s.start : s.end] for s in spans if s.role == SpanRole.DIRECT_PII]
        self.assertTrue(any("Thangjam\u200dchaobi Devi" in t for t in pii_texts))
        self.assertTrue(any("Kshetrimayum\u00a0Biren" in t for t in pii_texts))
        self.assertTrue(any("Zylomed-XR 250 mg BD x 7 days" in c for c in rec.clinical_attributes))

    def test_empty_and_malformed_values_do_not_crash(self) -> None:
        for val in ("", "   ", "N/A", "---", "null", "\u200b\u200d"):
            rec, spans = self._analyze(val)
            self.assertEqual(spans, [])
            self.assertEqual(rec.clinical_attributes, [])


if __name__ == "__main__":
    unittest.main()
