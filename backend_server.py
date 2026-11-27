# Purpose: Lightweight HTTP REST API server bridging React+TypeScript UI with the RAKSHA pipeline.
"""Backend API server for RAKSHA React+TypeScript UI."""

from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import tempfile
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import parse_qs, urlparse

from src.contracts import (
    ClinicalGuard,
    DetectionSpan,
    FieldNode,
    FileFormat,
    ParseStatus,
    PatientCluster,
    PatientRecord,
    PIIDetector,
    PrivacyDecision,
    SpanRole,
    TransformType,
)
from src.ingestion import UniversalIngestor
from src.linkage.engine import ConservativeLinkageEngine
from src.pipeline import RakshaPipeline
from src.privacy.engine import AdaptivePrivacyEngine
from src.serialization import SafeOutputSerializer

HOST = "127.0.0.1"
PORT = 8000

# Working directory for the UI session
UI_WORKSPACE = Path(".raksha_ui_workspace")
INPUT_DIR = UI_WORKSPACE / "input"
OUTPUT_DIR = UI_WORKSPACE / "output"

# Ensure environment secret is set
if "RAKSHA_SECRET" not in os.environ or not os.environ["RAKSHA_SECRET"].strip():
    os.environ["RAKSHA_SECRET"] = "RAKSHA-HACKATHON-DEAN-KEY-2026-STABLE"

# --- High-Precision Multilingual Detector & Clinical Guard for UI Demo ---

CLINICAL_PATTERNS = [
    re.compile(r"\b(?:BP|B\.P\.|Blood Pressure)\s*[:=]?\s*\d{2,3}/\d{2,3}\s*(?:mmHg)?\b", re.IGNORECASE),
    re.compile(r"\b(?:Pulse|HR|Heart Rate)\s*[:=]?\s*\d{2,3}\s*(?:bpm|/min)?\b", re.IGNORECASE),
    re.compile(r"\b(?:SpO2|SPO2|Oxygen Saturation)\s*[:=]?\s*\d{2,3}\s*%\b", re.IGNORECASE),
    re.compile(r"\b(?:Temp|Temperature)\s*[:=]?\s*\d{2,3}(?:\.\d)?\s*(?:°?F|°?C)?\b", re.IGNORECASE),
    re.compile(r"\b(?:RR|Respiratory Rate)\s*[:=]?\s*\d{1,2}\s*(?:/min|breaths/min)?\b", re.IGNORECASE),
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|ug|g|gm|ml|mL|IU|units?|mEq|mEq/L|mmol/L)\b", re.IGNORECASE),
    re.compile(r"\b(?:OD|BD|TDS|QID|Q4H|Q6H|HS|PRN|SOS|STAT|PO|IV|IM|SC|SL)\b"),
    re.compile(r"\b[01]-[01]-[01](?:-[01])?\b"),
    re.compile(r"\b(?:Tab|Tablet|Cap|Capsule|Syp|Syrup|Inj|Injection|Ointment)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:Paracetamol|Metformin|Ramipril|Amlodipine|Atorvastatin|Aspirin|Pantoprazole|"
        r"Omeprazole|Amoxicillin|Azithromycin|Ceftriaxone|Ciprofloxacin|Dolo|PCM|"
        r"Insulin|Glargine|Regular|Lispro|Furosemide|Hydrochlorothiazide|Losartan|"
        r"Telmisartan|Levothyroxine|Salbutamol|Budesonide|Cetirizine|Montelukast)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:Type 2 Diabetes Mellitus|Type 1 Diabetes|Diabetes|T2DM|T1DM|Hypertension|HTN|"
        r"Dengue|Dengue Fever|Malaria|Pneumonia|COVID-19|Myocardial Infarction|MI|CAD|"
        r"Asthma|COPD|Chronic Kidney Disease|CKD|Acute Kidney Injury|AKI|Stroke|CVA|"
        r"Tuberculosis|TB|Typhoid|Sepsis|Anemia|Hypothyroidism|Hyperthyroidism|"
        r"मधुमेह|डायबिटीज|उच्च रक्तचाप|डेंगू|मलेरिया|निमोनिया|हृदय रोग)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:HbA1c|Hemoglobin|WBC|RBC|Platelets?|Creatinine|BUN|Urea|Bilirubin|"
        r"SGOT|SGPT|ALT|AST|Alkaline Phosphatase|Total Cholesterol|Triglycerides|"
        r"HDL|LDL|VLDL|Serum Electrolytes|Na\+|K\+|Cl\-)\b",
        re.IGNORECASE,
    ),
]

PHONE_PATTERN = re.compile(r"(?:\+?91[\-\s]?)?[6-9]\d{9}\b")
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
ATTACHMENT_FILENAME_PATTERN = re.compile(
    r"\b[A-Za-z0-9][A-Za-z0-9_\-\.]*\.(?:pdf|docx?|xlsx?|png|jpe?g|tiff?|bmp|gif)\b",
    re.IGNORECASE,
)
AADHAAR_PATTERN = re.compile(r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b")
ABHA_PATTERN = re.compile(r"\b(?:ABHA[\-:]?\s*)?\d{2}[\-]\d{4}[\-]\d{4}[\-]\d{4}\b|\bABHA\|\d+\b", re.IGNORECASE)
PAN_PATTERN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
LOCAL_ID_PATTERN = re.compile(r"\b(?:MRN|UHID|PAT|IPD|OPD)[\-#:]?\s*[A-Z0-9]{4,12}\b", re.IGNORECASE)
PINCODE_PATTERN = re.compile(r"\b[1-9]\d{2}\s?\d{3}\b")
DATE_PATTERN = re.compile(r"\b(?:\d{4}[\-/]\d{2}[\-/]\d{2}|\d{2}[\-/]\d{2}[\-/]\d{4})\b")
AGE_PATTERN = re.compile(r"\b(?:Age\s*[:=]?\s*(\d{1,3})|(\d{1,3})\s*(?:years?|yrs?|yr|y/o|साल|वर्ष))\b", re.IGNORECASE)
NAME_CUES_EN = re.compile(r"\b(?:Patient|Pt|Name|Mr\.|Mrs\.|Ms\.|Dr\.|Shri|Smt)\s*[:=]?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b")
NAME_CUES_HI = re.compile(
    r"(?:मरीज|रोगी|नाम|श्री|श्रीमती|डॉ\.)\s*[:=]?\s*"
    r"((?!सुरक्षित|रखें|रखने|की|को|का|के|में|से|ने|है|हैं)[\u0900-\u097F]+"
    r"(?:\s+(?!सुरक्षित|रखें|रखने|की|को|का|के|में|से|ने|है|हैं)[\u0900-\u097F]+){1,2})"
)


STRUCTURED_TEXT_PII_PATTERNS = (
    ("PATIENT_NAME", re.compile(r'"(?:patient_?)?name"\s*:\s*"([^"\r\n]+)"', re.IGNORECASE)),
    ("PHONE", re.compile(r'"(?:phone|mobile|telephone|contact(?:_?number)?)"\s*:\s*"([^"\r\n]+)"', re.IGNORECASE)),
    ("ADDRESS", re.compile(r'"(?:address|residential_?address|location)"\s*:\s*"([^"\r\n]+)"', re.IGNORECASE)),
    ("EMAIL", re.compile(r'"(?:email|e_?mail)"\s*:\s*"([^"\r\n]+)"', re.IGNORECASE)),
)


class UIPIIDetector(PIIDetector):
    def analyze_record(self, record: PatientRecord) -> list[DetectionSpan]:
        spans: list[DetectionSpan] = []
        attrs = record.extracted_patient_attributes

        for node in record.fields:
            text = node.raw_value
            if not text:
                continue

            is_name_field = any(k in node.header_key.lower() for k in ("name", "patient_name", "pt_name", "naam"))
            if is_name_field and text.strip():
                spans.append(
                    DetectionSpan(
                        record_ref=record.record_ref,
                        field_path=node.field_path,
                        start=0,
                        end=len(text),
                        category="PATIENT_NAME",
                        role=SpanRole.DIRECT_PII,
                        confidence=0.98,
                        detector_source="ui_detector_key",
                    )
                )
                attrs.setdefault("PATIENT_NAME", []).append(text.strip())
                attrs.setdefault("names", []).append(text.strip())
            else:
                for match in NAME_CUES_EN.finditer(text):
                    start, end = match.span(1)
                    val = match.group(1).strip()
                    spans.append(
                        DetectionSpan(
                            record_ref=record.record_ref,
                            field_path=node.field_path,
                            start=start,
                            end=end,
                            category="PATIENT_NAME",
                            role=SpanRole.DIRECT_PII,
                            confidence=0.92,
                            detector_source="ui_detector_en_cue",
                        )
                    )
                    attrs.setdefault("PATIENT_NAME", []).append(val)
                    attrs.setdefault("names", []).append(val)

                for match in NAME_CUES_HI.finditer(text):
                    start, end = match.span(1)
                    val = match.group(1).strip()
                    spans.append(
                        DetectionSpan(
                            record_ref=record.record_ref,
                            field_path=node.field_path,
                            start=start,
                            end=end,
                            category="PATIENT_NAME",
                            role=SpanRole.DIRECT_PII,
                            confidence=0.95,
                            detector_source="ui_detector_hi_cue",
                        )
                    )
                    attrs.setdefault("PATIENT_NAME", []).append(val)
                    attrs.setdefault("names", []).append(val)

            # Text exports can contain JSON-style keys even when their filename
            # ends in .txt. Protect those explicit PII values as structured data.
            for category, pattern in STRUCTURED_TEXT_PII_PATTERNS:
                for match in pattern.finditer(text):
                    start, end = match.span(1)
                    value = match.group(1).strip()
                    if not value:
                        continue
                    spans.append(
                        DetectionSpan(
                            record_ref=record.record_ref,
                            field_path=node.field_path,
                            start=start,
                            end=end,
                            category=category,
                            role=SpanRole.DIRECT_PII,
                            confidence=0.99,
                            detector_source="ui_detector_structured_text",
                        )
                    )
                    if category == "PATIENT_NAME":
                        attrs.setdefault("PATIENT_NAME", []).append(value)
                        attrs.setdefault("names", []).append(value)
                    elif category == "PHONE":
                        phone = re.sub(r"\D", "", value)
                        attrs.setdefault("PHONE", []).append(phone)
                        attrs.setdefault("phones", []).append(phone)

            # Identifiers
            for m in ABHA_PATTERN.finditer(text):
                clean_id = m.group(0).strip()
                spans.append(
                    DetectionSpan(
                        record_ref=record.record_ref,
                        field_path=node.field_path,
                        start=m.start(),
                        end=m.end(),
                        category="PATIENT_IDENTIFIER",
                        role=SpanRole.DIRECT_PII,
                        confidence=0.99,
                        detector_source="ui_detector_abha",
                    )
                )
                attrs.setdefault("ids", []).append(f"ABHA|{clean_id}")
                attrs.setdefault("ABHA", []).append(clean_id)

            for m in AADHAAR_PATTERN.finditer(text):
                clean_id = m.group(0).strip()
                spans.append(
                    DetectionSpan(
                        record_ref=record.record_ref,
                        field_path=node.field_path,
                        start=m.start(),
                        end=m.end(),
                        category="PATIENT_IDENTIFIER",
                        role=SpanRole.DIRECT_PII,
                        confidence=0.96,
                        detector_source="ui_detector_aadhaar",
                    )
                )
                attrs.setdefault("ids", []).append(f"AADHAAR|{clean_id}")
                attrs.setdefault("AADHAAR", []).append(clean_id)

            for m in PHONE_PATTERN.finditer(text):
                clean_phone = re.sub(r"\D", "", m.group(0))[-10:]
                spans.append(
                    DetectionSpan(
                        record_ref=record.record_ref,
                        field_path=node.field_path,
                        start=m.start(),
                        end=m.end(),
                        category="PHONE",
                        role=SpanRole.DIRECT_PII,
                        confidence=0.97,
                        detector_source="ui_detector_phone",
                    )
                )
                attrs.setdefault("PHONE", []).append(clean_phone)
                attrs.setdefault("phones", []).append(clean_phone)

            for m in EMAIL_PATTERN.finditer(text):
                spans.append(
                    DetectionSpan(
                        record_ref=record.record_ref,
                        field_path=node.field_path,
                        start=m.start(),
                        end=m.end(),
                        category="EMAIL",
                        role=SpanRole.DIRECT_PII,
                        confidence=0.98,
                        detector_source="ui_detector_email",
                    )
                )

            for m in ATTACHMENT_FILENAME_PATTERN.finditer(text):
                spans.append(
                    DetectionSpan(
                        record_ref=record.record_ref,
                        field_path=node.field_path,
                        start=m.start(),
                        end=m.end(),
                        category="ATTACHMENT",
                        role=SpanRole.DIRECT_PII,
                        confidence=0.96,
                        detector_source="ui_detector_attachment",
                    )
                )

            # Dates
            is_date_field = any(k in node.header_key.lower() for k in ("date", "dob", "birth", "admit", "discharge"))
            if is_date_field or re.search(r"^\d{4}-\d{2}-\d{2}$", text.strip()):
                spans.append(
                    DetectionSpan(
                        record_ref=record.record_ref,
                        field_path=node.field_path,
                        start=0,
                        end=len(text),
                        category="DATE",
                        role=SpanRole.QUASI_IDENTIFIER,
                        confidence=0.96,
                        detector_source="ui_detector_date_field",
                    )
                )
                attrs.setdefault("dobs", []).append(text.strip())
            else:
                for m in DATE_PATTERN.finditer(text):
                    spans.append(
                        DetectionSpan(
                            record_ref=record.record_ref,
                            field_path=node.field_path,
                            start=m.start(),
                            end=m.end(),
                            category="DATE",
                            role=SpanRole.QUASI_IDENTIFIER,
                            confidence=0.92,
                            detector_source="ui_detector_date_regex",
                        )
                    )

            # Age
            is_age_field = any(k in node.header_key.lower() for k in ("age", "aayu", "umar"))
            if is_age_field and text.strip().isdigit():
                spans.append(
                    DetectionSpan(
                        record_ref=record.record_ref,
                        field_path=node.field_path,
                        start=0,
                        end=len(text),
                        category="AGE",
                        role=SpanRole.QUASI_IDENTIFIER,
                        confidence=0.99,
                        detector_source="ui_detector_age_field",
                    )
                )
                attrs.setdefault("ages", []).append(text.strip())
            else:
                for m in AGE_PATTERN.finditer(text):
                    group_idx = 1 if m.group(1) else 2
                    age_val = m.group(group_idx)
                    a_start, a_end = m.span(group_idx)
                    spans.append(
                        DetectionSpan(
                            record_ref=record.record_ref,
                            field_path=node.field_path,
                            start=a_start,
                            end=a_end,
                            category="AGE",
                            role=SpanRole.QUASI_IDENTIFIER,
                            confidence=0.94,
                            detector_source="ui_detector_age_regex",
                        )
                    )
                    if age_val:
                        attrs.setdefault("ages", []).append(age_val)

        # Propagate detected patient names across all fields in the record so
        # repeated mentions in notes or attachment filenames are also redacted.
        known_names = {
            n.strip()
            for n in attrs.get("PATIENT_NAME", [])
            if len(n.strip()) >= 4 and n.strip().casefold() not in {"self", "unknown"}
        }
        if known_names:
            for node in record.fields:
                text = node.raw_value
                if not text:
                    continue
                existing = [
                    (s.start, s.end)
                    for s in spans
                    if s.field_path == node.field_path
                ]
                for name in sorted(known_names, key=len, reverse=True):
                    pat = re.compile(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", re.IGNORECASE)
                    for m in pat.finditer(text):
                        s_idx, e_idx = m.span()
                        if any(not (e_idx <= es or s_idx >= ee) for es, ee in existing):
                            continue
                        spans.append(
                            DetectionSpan(
                                record_ref=record.record_ref,
                                field_path=node.field_path,
                                start=s_idx,
                                end=e_idx,
                                category="PATIENT_NAME",
                                role=SpanRole.DIRECT_PII,
                                confidence=0.90,
                                detector_source="ui_detector_name_propagation",
                            )
                        )
                        existing.append((s_idx, e_idx))

        return spans


class UIClinicalGuard(ClinicalGuard):
    def protect_clinical(
        self, record: PatientRecord, spans: Sequence[DetectionSpan]
    ) -> tuple[list[DetectionSpan], list[str]]:
        protected_spans: list[DetectionSpan] = []
        clinical_attributes: list[str] = []
        clinical_spans_found: list[DetectionSpan] = []

        for node in record.fields:
            text = node.raw_value
            if not text:
                continue
            for pat in CLINICAL_PATTERNS:
                for match in pat.finditer(text):
                    start, end = match.span()
                    val = match.group(0).strip()
                    cspan = DetectionSpan(
                        record_ref=record.record_ref,
                        field_path=node.field_path,
                        start=start,
                        end=end,
                        category="CLINICAL_TERM",
                        role=SpanRole.CLINICAL_PROTECTED,
                        confidence=1.0,
                        detector_source="ui_clinical_guard",
                    )
                    clinical_spans_found.append(cspan)
                    clinical_attributes.append(val)

        for pii_span in spans:
            overlaps = any(
                c.field_path == pii_span.field_path
                and pii_span.start < c.end
                and pii_span.end > c.start
                for c in clinical_spans_found
            )
            if overlaps:
                protected_spans.append(
                    DetectionSpan(
                        record_ref=pii_span.record_ref,
                        field_path=pii_span.field_path,
                        start=pii_span.start,
                        end=pii_span.end,
                        category=pii_span.category,
                        role=SpanRole.CLINICAL_PROTECTED,
                        confidence=1.0,
                        detector_source="clinical_override",
                    )
                )
            else:
                protected_spans.append(pii_span)

        for c in clinical_spans_found:
            if not any(
                p.field_path == c.field_path and p.start == c.start and p.end == c.end
                for p in protected_spans
            ):
                protected_spans.append(c)

        return protected_spans, list(set(clinical_attributes))


class ComprehensiveUIPrivacyEngine:
    """Wraps AdaptivePrivacyEngine and ensures direct PII without explicit decisions receives redaction."""

    def __init__(self) -> None:
        self.base = AdaptivePrivacyEngine()

    def transform(
        self,
        records: Sequence[PatientRecord],
        clusters: Sequence[PatientCluster],
        secret_key: bytes,
    ) -> list[PrivacyDecision]:
        decisions = self.base.transform(records, clusters, secret_key)
        covered = {(d.record_ref, d.field_path, d.start, d.end) for d in decisions if d.start is not None}
        for rec in records:
            for s in rec.detections:
                if s.role == SpanRole.DIRECT_PII and (s.record_ref, s.field_path, s.start, s.end) not in covered:
                    tag = f"[REDACTED-{s.category}]" if s.category else "[REDACTED]"
                    decisions.append(
                        PrivacyDecision(
                            record_ref=s.record_ref,
                            field_path=s.field_path,
                            start=s.start,
                            end=s.end,
                            transform_type=TransformType.REDACT,
                            replacement_value=tag,
                        )
                    )
        return decisions


# --- Preset Scenario Definitions ---

PRESETS = {
    "multilingual-linkage": {
        "title": "Cross-Hospital Multilingual Linkage",
        "description": "Demonstrates cross-hospital linkage of patient Aarav Sharma / आरव शर्मा across Apollo CSV, AIIMS Hindi text, and FHIR R4 JSON.",
        "files": {
            "apollo_ward_a.csv": (
                "id,patient_name,dob,phone,abha,diagnosis,prescribed\n"
                "1,Aarav Sharma,1984-06-15,9876543210,12-3456-7890-1234,Type 2 Diabetes,Metformin 500mg BD\n"
                "2,Priya Nair,1992-11-04,9123456780,98-7654-3210-9876,Hypertension,Amlodipine 5mg OD\n"
            ),
            "aiims_icu_note_hindi.txt": (
                "अस्पताल: एम्स नई दिल्ली - आईसीयू परामर्श नोट\n"
                "दिनांक: 2024-03-20\n"
                "मरीज: आरव शर्मा, फोन: 9876543210, एबीएचए: 12-3456-7890-1234\n"
                "रक्तचाप (BP): 130/85 mmHg, नाड़ी (Pulse): 74/min, SpO2: 98%\n"
                "चिकित्सा निदान: मधुमेह (Type 2 Diabetes)\n"
                "दवाएं: Metformin 500mg BD, Dolo 650 SOS, Tab Pantoprazole 40mg OD\n"
            ),
            "diagnostic_report.fhir.json": json.dumps(
                {
                    "resourceType": "Bundle",
                    "type": "collection",
                    "entry": [
                        {
                            "resource": {
                                "resourceType": "Patient",
                                "id": "pat-001",
                                "identifier": [
                                    {"system": "https://abdm.gov.in/abha", "value": "12-3456-7890-1234"}
                                ],
                                "name": [{"family": "Sharma", "given": ["Aarav"]}],
                                "birthDate": "1984-06-15",
                                "telecom": [{"system": "phone", "value": "9876543210"}],
                            }
                        },
                        {
                            "resource": {
                                "resourceType": "Observation",
                                "id": "obs-001",
                                "status": "final",
                                "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4", "display": "HbA1c"}]},
                                "valueQuantity": {"value": 7.4, "unit": "%"},
                            }
                        },
                    ],
                },
                indent=2,
            ),
        },
    },
    "clinical-preservation": {
        "title": "ICU Clinical Safety & Dosage Preservation",
        "description": "Verifies that vital signs (BP 165/95, SpO2 94%), critical medications (Ramipril, Insulin Glargine), and exact dosage regimens are 100% preserved while doctor and patient identifiers are safely transformed.",
        "files": {
            "icu_rounds.tsv": (
                "Bed\tPatient\tDoctor\tVitals\tRegimen\n"
                "ICU-04\tSunita Verma\tDr. Rajesh K\tBP 165/95 mmHg, HR 88 bpm, SpO2 94%\tRamipril 5mg OD, Insulin Glargine 14 units at HS\n"
                "ICU-07\tVikram Joshi\tDr. Sneha Patil\tBP 120/80 mmHg, SpO2 99%\tParacetamol 650mg TDS, Metformin 1000mg BD\n"
            ),
            "discharge_summary.txt": (
                "CITY CARE HOSPITAL - DISCHARGE SUMMARY\n"
                "Patient: Sunita Verma, Age: 58 years, Phone: 9811223344\n"
                "Attending Physician: Dr. Rajesh K\n"
                "Admission Date: 2024-02-10 | Discharge Date: 2024-02-18\n"
                "Final Diagnosis: Severe Hypertension, Uncontrolled T2DM\n"
                "Discharge Vitals: BP 128/82 mmHg, Pulse 72/min, Temp 98.4 F, SpO2 98%\n"
                "Discharge Medications:\n"
                "1. Tab Ramipril 5mg - 1-0-0 (Morning after food)\n"
                "2. Inj Insulin Glargine 14 units SC at bedtime (22:00)\n"
                "3. Tab Pantoprazole 40mg - 1-0-0 (Empty stomach)\n"
            ),
        },
    },
    "security-quarantine": {
        "title": "Hostile Attack & Quarantine Defense",
        "description": "Tests firewall immunity against path traversal, unsupported binaries, and corrupted encodings. Demonstrates how RAKSHA quarantines threats into report.json without crashing the pipeline.",
        "files": {
            "valid_clinic_data.csv": (
                "patient_id,name,diagnosis\n"
                "P101,Kavita Rao,Mild Asthma\n"
            ),
            "malicious_traversal..attack.csv": (
                "target,content\n"
                "../../etc/passwd,malicious_payload\n"
            ),
            "corrupted_binary.bin": "RIFF\x00\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x44\xac\x00\x00",
        },
    },
}


def ensure_workspace() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


class RakshaAPIHandler(BaseHTTPRequestHandler):
    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def _send_json(self, status: int, data: Any) -> None:
        raw = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        ensure_workspace()

        if path == "/api/status":
            secret = os.environ.get("RAKSHA_SECRET", "")
            self._send_json(
                200,
                {
                    "status": "ready",
                    "version": "1.0.0",
                    "secret_set": bool(secret),
                    "secret_hint": secret[:4] + "..." + secret[-4:] if len(secret) >= 8 else "set",
                    "input_files": len(list(INPUT_DIR.iterdir())) if INPUT_DIR.exists() else 0,
                    "has_output": (OUTPUT_DIR / "report.json").exists(),
                },
            )
            return

        if path == "/api/presets":
            summary = {
                k: {"title": v["title"], "description": v["description"], "file_count": len(v["files"])}
                for k, v in PRESETS.items()
            }
            self._send_json(200, summary)
            return

        if path == "/api/files":
            files_info = []
            if INPUT_DIR.exists():
                for p in sorted(INPUT_DIR.iterdir()):
                    if p.is_file():
                        size = p.stat().st_size
                        ext = p.suffix.lower()
                        fmt = "csv" if ext == ".csv" else "tsv" if ext == ".tsv" else "fhir_r4" if ".fhir." in p.name else "json" if ext == ".json" else "text" if ext == ".txt" else "unsupported"
                        preview = ""
                        try:
                            preview = p.read_text(encoding="utf-8", errors="replace")[:300]
                        except Exception:
                            preview = f"[Binary / Unreadable, {size} bytes]"
                        files_info.append({
                            "name": p.name,
                            "size": size,
                            "format": fmt,
                            "preview": preview,
                        })
            self._send_json(200, {"files": files_info})
            return

        if path == "/api/report":
            report_file = OUTPUT_DIR / "report.json"
            records_file = OUTPUT_DIR / "records.jsonl"
            if not report_file.exists():
                self._send_json(404, {"error": "Pipeline has not run yet. No report.json found."})
                return
            report = json.loads(report_file.read_text(encoding="utf-8"))
            records = []
            if records_file.exists():
                for line in records_file.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        records.append(json.loads(line))
            self._send_json(200, {"report": report, "records": records})
            return

        if path == "/api/diff":
            filename = query.get("file", [""])[0]
            if not filename:
                self._send_json(400, {"error": "Missing 'file' parameter"})
                return

            original_path = INPUT_DIR / filename
            sanitized_path = OUTPUT_DIR / "sanitized" / filename

            if not original_path.exists():
                self._send_json(404, {"error": f"Original file {filename} not found"})
                return

            orig_text = ""
            max_preview_chars = 262144
            try:
                orig_text = original_path.read_text(encoding="utf-8", errors="replace")
                if len(orig_text) > max_preview_chars:
                    orig_text = orig_text[:max_preview_chars] + f"\n\n... [Preview truncated: file is {original_path.stat().st_size:,} bytes]"
            except Exception:
                orig_text = f"[Binary data: {original_path.stat().st_size} bytes]"

            san_text = None
            status = "sanitized"
            if sanitized_path.exists():
                try:
                    san_text = sanitized_path.read_text(encoding="utf-8", errors="replace")
                    if len(san_text) > max_preview_chars:
                        san_text = san_text[:max_preview_chars] + f"\n\n... [Preview truncated: file is {sanitized_path.stat().st_size:,} bytes]"
                except Exception:
                    san_text = f"[Binary data: {sanitized_path.stat().st_size} bytes]"
            else:
                status = "quarantined"

            self._send_json(
                200,
                {
                    "filename": filename,
                    "status": status,
                    "original": orig_text,
                    "sanitized": san_text,
                },
            )
            return

        if path == "/api/download-zip":
            if not OUTPUT_DIR.exists() or not (OUTPUT_DIR / "report.json").exists():
                self._send_json(404, {"error": "No output available to download."})
                return

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for root, _, files in os.walk(OUTPUT_DIR):
                    for file in files:
                        full_path = Path(root) / file
                        arcname = full_path.relative_to(OUTPUT_DIR)
                        zip_file.write(full_path, arcname)

            zip_buffer.seek(0)
            data = zip_buffer.getvalue()

            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", 'attachment; filename="raksha_sanitized_package.zip"')
            self.send_header("Content-Length", str(len(data)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(data)
            return

        # Serve React frontend dist files for GET requests
        dist_dir = Path("frontend/dist")
        if dist_dir.exists():
            req_file = (dist_dir / path.lstrip("/")).resolve()
            if path == "/" or not req_file.exists() or not req_file.is_file():
                req_file = dist_dir / "index.html"

            if req_file.exists() and req_file.is_file():
                content_type = "text/html; charset=utf-8"
                if req_file.suffix == ".js":
                    content_type = "application/javascript; charset=utf-8"
                elif req_file.suffix == ".css":
                    content_type = "text/css; charset=utf-8"
                elif req_file.suffix == ".json":
                    content_type = "application/json; charset=utf-8"
                elif req_file.suffix == ".svg":
                    content_type = "image/svg+xml"
                elif req_file.suffix in (".png", ".jpg", ".jpeg"):
                    content_type = f"image/{req_file.suffix.lstrip('.')}"

                file_bytes = req_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(file_bytes)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(file_bytes)
                return

        self._send_json(404, {"error": f"Endpoint not found: {path}"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        ensure_workspace()

        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len > 0 else b""

        if path == "/api/load-preset":
            payload = json.loads(body.decode("utf-8") or "{}")
            preset_key = payload.get("preset", "multilingual-linkage")
            if preset_key not in PRESETS:
                self._send_json(400, {"error": f"Invalid preset: {preset_key}"})
                return

            # Clear input & output
            shutil.rmtree(INPUT_DIR, ignore_errors=True)
            shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
            ensure_workspace()

            preset_data = PRESETS[preset_key]
            loaded_files = []
            for fname, content in preset_data["files"].items():
                target = INPUT_DIR / fname
                if isinstance(content, str):
                    target.write_text(content, encoding="utf-8")
                else:
                    target.write_bytes(content)
                loaded_files.append(fname)

            self._send_json(
                200,
                {
                    "success": True,
                    "preset": preset_key,
                    "title": preset_data["title"],
                    "loaded_files": loaded_files,
                },
            )
            return

        if path == "/api/upload":
            content_type = self.headers.get("Content-Type", "")
            if "application/json" in content_type:
                payload = json.loads(body.decode("utf-8"))
                filename = payload.get("filename", f"upload_{int(time.time())}.txt")
                content = payload.get("content", "")
                is_base64 = payload.get("is_base64", False)

                target = INPUT_DIR / filename
                if is_base64:
                    target.write_bytes(base64.b64decode(content))
                else:
                    target.write_text(content, encoding="utf-8")

                self._send_json(200, {"success": True, "filename": filename, "size": target.stat().st_size})
                return
            else:
                self._send_json(400, {"error": "Upload via JSON {filename, content, is_base64} recommended"})
                return

        if path == "/api/reset":
            shutil.rmtree(INPUT_DIR, ignore_errors=True)
            shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
            ensure_workspace()
            self._send_json(200, {"success": True, "message": "Workspace reset."})
            return

        if path == "/api/delete-file":
            payload = json.loads(body.decode("utf-8") or "{}")
            filename = payload.get("filename", "")
            target = INPUT_DIR / filename
            if target.exists() and target.is_file():
                target.unlink()
                self._send_json(200, {"success": True, "message": f"Deleted {filename}"})
            else:
                self._send_json(404, {"error": f"File {filename} not found"})
            return

        if path == "/api/run":
            if not INPUT_DIR.exists() or not list(INPUT_DIR.iterdir()):
                self._send_json(400, {"error": "No input files found. Please upload files or load a preset."})
                return

            shutil.rmtree(OUTPUT_DIR, ignore_errors=True)
            ensure_workspace()

            pipeline = RakshaPipeline(
                detector=UIPIIDetector(),
                clinical_guard=UIClinicalGuard(),
                linker=ConservativeLinkageEngine(),
                privacy_engine=ComprehensiveUIPrivacyEngine(),
                serializer=SafeOutputSerializer(),
            )

            start_t = time.perf_counter()
            try:
                metrics = pipeline.run(input_dir=INPUT_DIR, output_dir=OUTPUT_DIR)
            except Exception as exc:
                self._send_json(500, {"error": f"Pipeline failed: {exc}"})
                return
            duration = time.perf_counter() - start_t

            # Read report.json and records.jsonl
            report = json.loads((OUTPUT_DIR / "report.json").read_text(encoding="utf-8"))
            records = []
            rec_file = OUTPUT_DIR / "records.jsonl"
            if rec_file.exists():
                for line in rec_file.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        records.append(json.loads(line))

            # Build clinical preservation list and diff summaries
            sanitized_dir = OUTPUT_DIR / "sanitized"
            sanitized_files = [p.name for p in sanitized_dir.iterdir()] if sanitized_dir.exists() else []

            # Group patient clusters for visual graph
            clusters_map: dict[str, list[dict]] = {}
            for rec in records:
                psn = rec.get("pseudonym_id") or "UNRESOLVED"
                clusters_map.setdefault(psn, []).append({
                    "record_ref": rec.get("record_ref"),
                    "source_ref": rec.get("source_ref"),
                    "pseudonym_id": rec.get("pseudonym_id"),
                    "cluster_ref": rec.get("cluster_ref"),
                    "field_count": len(rec.get("fields", [])),
                    "identifiers": rec.get("identifiers_detected", 0),
                })

            self._send_json(
                200,
                {
                    "success": True,
                    "metrics": {
                        "files_total": metrics.files_total,
                        "files_sanitized": metrics.files_sanitized,
                        "files_quarantined": metrics.files_quarantined,
                        "records_processed": metrics.records_processed,
                        "identifiers_detected": metrics.identifiers_detected,
                        "records_linked": metrics.records_linked,
                        "records_generalized": metrics.records_generalized,
                        "records_suppressed": metrics.records_suppressed,
                        "seconds": round(duration, 4),
                        "peak_rss_mb": round(metrics.peak_rss_mb, 2),
                    },
                    "report": report,
                    "records_count": len(records),
                    "clusters": clusters_map,
                    "sanitized_files": sanitized_files,
                },
            )
            return

        self._send_json(404, {"error": f"Endpoint not found: {path}"})


def run_server() -> None:
    ensure_workspace()
    server = ThreadingHTTPServer((HOST, PORT), RakshaAPIHandler)
    print(f"[*] RAKSHA Backend API Server running at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        server.shutdown()


if __name__ == "__main__":
    run_server()
