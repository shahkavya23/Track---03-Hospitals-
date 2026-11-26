# Purpose: Tests format-preserving serialization, clinical integrity guards, filename/key renaming, and report.json/records.jsonl validation.
"""Tests for safe serialization, reporting, and leak validation."""

from __future__ import annotations

import base64
import csv
import json
import os
import tempfile
import unittest
from pathlib import Path

from src.contracts import (
    AuditMetrics,
    DetectionSpan,
    FileReportEntry,
    ParseStatus,
    PrivacyDecision,
    SpanRole,
    TransformType,
)
from src.ingestion import UniversalIngestor
from src.reporting import write_records_jsonl, write_report_json
from src.serialization import (
    OutputValidationError,
    SafeOutputSerializer,
    apply_decisions_to_field,
    validate_serialized_output,
)


class SerializationAndReportingTests(unittest.TestCase):
    def test_reverse_offset_splicing_and_clinical_guard_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_dir = Path(tmp) / "in"
            in_dir.mkdir()
            note = (
                "Arif sahab ka BP 150/90, phone 9876543210, "
                "Dolo 650 BD x 5 days, Ramipril 5 mg, HbA1c 7.4%, 1-0-1"
            )
            (in_dir / "note.txt").write_text(note, encoding="utf-8")
            sources = UniversalIngestor().ingest_directory(in_dir)
            rec = sources[0].records[0]

            # Protect all clinical terms
            for term in ("BP 150/90", "Dolo 650 BD x 5 days", "Ramipril 5 mg", "HbA1c 7.4%", "1-0-1"):
                idx = note.index(term)
                rec.detections.append(
                    DetectionSpan(
                        rec.record_ref, "doc", idx, idx + len(term),
                        "CLINICAL", SpanRole.CLINICAL_PROTECTED, 1.0, "guard",
                    )
                )
                rec.clinical_attributes.append(term)

            # Valid PII edits + an adversarial/buggy edit attempting to overwrite Ramipril 5 mg
            ramipril_idx = note.index("Ramipril 5 mg")
            phone_idx = note.index("9876543210")
            rec.privacy_decisions.extend([
                PrivacyDecision(rec.record_ref, "doc", 0, 10, TransformType.PSEUDONYMIZE, "PSN-ABC123"),
                PrivacyDecision(rec.record_ref, "doc", phone_idx, phone_idx + 10, TransformType.REDACT, "[PHONE]"),
                PrivacyDecision(rec.record_ref, "doc", ramipril_idx, ramipril_idx + 8, TransformType.REDACT, "[BAD]"),
            ])

            transformed, blocked = apply_decisions_to_field(note, rec, "doc")
            self.assertEqual(blocked, 1)
            self.assertIn("PSN-ABC123", transformed)
            self.assertIn("[PHONE]", transformed)
            self.assertNotIn("9876543210", transformed)
            self.assertNotIn("[BAD]", transformed)
            for term in ("BP 150/90", "Dolo 650 BD x 5 days", "Ramipril 5 mg", "HbA1c 7.4%", "1-0-1"):
                self.assertIn(term, transformed)

    def test_end_to_end_multi_format_serialization_and_reporting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            in_dir = root / "input"
            out_dir = root / "output"
            (in_dir / "reg").mkdir(parents=True)
            (in_dir / "opd").mkdir(parents=True)
            (in_dir / "notes").mkdir(parents=True)

            # 1. Semicolon CSV with clinical values and PII header
            (in_dir / "reg" / "hosp.csv").write_text(
                "arif_custom_col;patient_name;regimen\n"
                "v1;Mohammad Arif;1-0-1\n"
                "v2;;Dolo 650 BD x 5 days\n",
                encoding="utf-8",
            )

            # 2. Multi-record JSON with PII inside key and value
            (in_dir / "opd" / "visits.json").write_text(
                json.dumps(
                    {
                        "hospital": "Ward 3",
                        "visits": [
                            {"patient/arif_key": "Mohammad Arif", "bp": "150/90"},
                            {"patient/arif_key": "Meera", "hba1c": "HbA1c 7.4%"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            # 3. FHIR R4 Bundle with base64 attachment containing Hindi + clinical text
            att_b64 = base64.b64encode("Patient: मोहम्मद आरिफ | Rx: Ramipril 5 mg".encode("utf-8")).decode()
            (in_dir / "opd" / "bundle.json").write_text(
                json.dumps(
                    {
                        "resourceType": "Bundle",
                        "type": "collection",
                        "entry": [
                            {"resource": {"resourceType": "Patient", "id": "raw-1", "name": [{"text": "Mohammad Arif"}]}},
                            {
                                "resource": {
                                    "resourceType": "DocumentReference",
                                    "content": [{"attachment": {"contentType": "text/plain", "data": att_b64}}],
                                }
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            # 4. Text file whose filename contains PII
            (in_dir / "notes" / "patient_mohammad_arif.txt").write_text(
                "Mohammad Arif admitted 2026-01-10, BP 150/90",
                encoding="utf-8",
            )

            # 5. Unsupported binary file -> quarantined
            (in_dir / "notes" / "scan.pdf").write_bytes(b"%PDF-1.4")

            sources = UniversalIngestor().ingest_directory(in_dir)
            by_rel = {s.relative_path: s for s in sources}

            # Simulate M2/M3 outputs on ingested records
            csv_src = by_rel["reg/hosp.csv"]
            csv_src.records[0].pseudonym_id = "PSN-ARIF01"
            csv_src.records[0].clinical_attributes = ["1-0-1"]
            csv_src.records[0].privacy_decisions = [
                PrivacyDecision(csv_src.records[0].record_ref, "@header:0", None, None, TransformType.REDACT, "col_0"),
                PrivacyDecision(csv_src.records[0].record_ref, "col:1:patient_name", 0, 13, TransformType.PSEUDONYMIZE, "PSN-ARIF01"),
            ]
            csv_src.records[1].pseudonym_id = None
            csv_src.records[1].clinical_attributes = ["Dolo 650 BD x 5 days"]

            visits_src = by_rel["opd/visits.json"]
            visits_src.records[0].pseudonym_id = "PSN-ARIF01"
            visits_src.records[0].clinical_attributes = ["150/90"]
            visits_src.records[0].privacy_decisions = [
                PrivacyDecision(visits_src.records[0].record_ref, "/visits/0/patient~1arif_key", 0, 13, TransformType.PSEUDONYMIZE, "PSN-ARIF01"),
                PrivacyDecision(visits_src.records[0].record_ref, "@key:/visits/0/patient~1arif_key", None, None, TransformType.REDACT, "patient_ref"),
            ]
            visits_src.records[1].pseudonym_id = "PSN-MEERA2"
            visits_src.records[1].clinical_attributes = ["HbA1c 7.4%"]
            visits_src.records[1].privacy_decisions = [
                PrivacyDecision(visits_src.records[1].record_ref, "/visits/1/patient~1arif_key", 0, 5, TransformType.PSEUDONYMIZE, "PSN-MEERA2"),
                PrivacyDecision(visits_src.records[1].record_ref, "@key:/visits/1/patient~1arif_key", None, None, TransformType.REDACT, "patient_ref"),
            ]

            fhir_src = by_rel["opd/bundle.json"]
            fhir_rec = fhir_src.records[0]
            fhir_rec.pseudonym_id = "PSN-ARIF01"
            fhir_rec.clinical_attributes = ["Ramipril 5 mg"]
            att_node = next(n for n in fhir_rec.fields if n.field_path.endswith("@decoded_attachment"))
            hindi_start = att_node.raw_value.index("मोहम्मद आरिफ")
            fhir_rec.privacy_decisions = [
                PrivacyDecision(fhir_rec.record_ref, "/entry/0/resource/name/0/text", 0, 13, TransformType.REDACT, "[NAME]"),
                PrivacyDecision(fhir_rec.record_ref, "/entry/0/resource/id", 0, 5, TransformType.PSEUDONYMIZE, "PSN-ARIF01"),
                PrivacyDecision(fhir_rec.record_ref, att_node.field_path, hindi_start, hindi_start + len("मोहम्मद आरिफ"), TransformType.PSEUDONYMIZE, "PSN-ARIF01"),
            ]

            txt_src = by_rel["notes/patient_mohammad_arif.txt"]
            txt_rec = txt_src.records[0]
            txt_rec.pseudonym_id = "PSN-ARIF01"
            txt_rec.clinical_attributes = ["BP 150/90"]
            txt_rec.field_metadata["filename_has_pii"] = True
            txt_rec.privacy_decisions = [
                PrivacyDecision(txt_rec.record_ref, "doc", 0, 13, TransformType.PSEUDONYMIZE, "PSN-ARIF01"),
            ]

            all_recs = [r for s in sources for r in s.records]
            metrics = AuditMetrics(
                files=[
                    FileReportEntry(
                        input_sha256=s.source_sha256,
                        output=s.sanitized_relative_path if s.parse_status == ParseStatus.PARSED else None,
                        status="sanitized" if s.parse_status == ParseStatus.PARSED else "quarantined",
                        reason=s.quarantine_reason,
                    )
                    for s in sources
                ],
                files_total=len(sources),
                files_sanitized=sum(1 for s in sources if s.parse_status == ParseStatus.PARSED),
                files_quarantined=sum(1 for s in sources if s.parse_status == ParseStatus.QUARANTINED),
                records_processed=len(all_recs),
                identifiers_detected=6,
                records_linked=sum(1 for r in all_recs if r.pseudonym_id is not None),
                seconds=0.12,
                peak_rss_mb=42.5,
            )

            SafeOutputSerializer().serialize_all(sources, out_dir, metrics)

            # Verify CSV semicolon format, renamed header, and preserved clinical strings
            csv_out = (out_dir / "sanitized" / "reg" / "hosp.csv").read_text(encoding="utf-8")
            rows = list(csv.reader(csv_out.splitlines(), delimiter=";"))
            self.assertEqual(rows[0], ["col_0", "patient_name", "regimen"])
            self.assertEqual(rows[1], ["v1", "PSN-ARIF01", "1-0-1"])
            self.assertEqual(rows[2], ["v2", "", "Dolo 650 BD x 5 days"])

            # Verify JSON key rename & clinical preservation
            visits_out = json.loads((out_dir / "sanitized" / "opd" / "visits.json").read_text(encoding="utf-8"))
            self.assertEqual(visits_out["hospital"], "Ward 3")
            self.assertEqual(visits_out["visits"][0]["patient_ref"], "PSN-ARIF01")
            self.assertEqual(visits_out["visits"][0]["bp"], "150/90")
            self.assertNotIn("patient/arif_key", json.dumps(visits_out))

            # Verify FHIR R4 Bundle & base64 attachment re-encoding
            fhir_out = json.loads((out_dir / "sanitized" / "opd" / "bundle.json").read_text(encoding="utf-8"))
            self.assertEqual(fhir_out["resourceType"], "Bundle")
            self.assertEqual(fhir_out["entry"][0]["resource"]["id"], "PSN-ARIF01")
            reencoded_att = fhir_out["entry"][1]["resource"]["content"][0]["attachment"]["data"]
            decoded_att = base64.b64decode(reencoded_att).decode("utf-8")
            self.assertIn("PSN-ARIF01", decoded_att)
            self.assertIn("Ramipril 5 mg", decoded_att)
            self.assertNotIn("मोहम्मद आरिफ", decoded_att)

            # Verify filename-PII rename & report/records consistency
            expected_renamed = f"sanitized/notes/doc_{txt_src.source_sha256[:12]}.txt"
            self.assertTrue((out_dir / expected_renamed).is_file())
            self.assertFalse((out_dir / "sanitized" / "notes" / "patient_mohammad_arif.txt").exists())
            self.assertFalse((out_dir / "sanitized" / "notes" / "scan.pdf").exists())

            report_txt = (out_dir / "report.json").read_text(encoding="utf-8")
            self.assertNotIn("patient_mohammad_arif.txt", report_txt)
            self.assertNotIn("scan.pdf", report_txt)
            report = json.loads(report_txt)
            self.assertEqual(report["counts"]["files_total"], 5)
            self.assertEqual(report["counts"]["files_sanitized"], 4)
            self.assertEqual(report["counts"]["files_quarantined"], 1)
            self.assertEqual(report["counts"]["records_processed"], 6)
            self.assertEqual(report["counts"]["records_linked"], 5)

            records_lines = [
                json.loads(line)
                for line in (out_dir / "records.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(records_lines), 6)
            by_file_loc = {(item["file"], item["loc"]): item["patient"] for item in records_lines}
            self.assertEqual(by_file_loc[("sanitized/reg/hosp.csv", "row:0")], "PSN-ARIF01")
            self.assertIsNone(by_file_loc[("sanitized/reg/hosp.csv", "row:1")])
            self.assertEqual(by_file_loc[("sanitized/opd/visits.json", "/visits/1")], "PSN-MEERA2")
            self.assertEqual(by_file_loc[(expected_renamed, "doc")], "PSN-ARIF01")

    def test_report_and_validator_catch_mismatches_and_leaks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            out_dir.mkdir()
            (out_dir / "sanitized").mkdir()

            bad_metrics = AuditMetrics(files=[], files_total=1, files_sanitized=1, files_quarantined=0)
            with self.assertRaises(ValueError):
                write_report_json(bad_metrics, out_dir)

            # Secret leak check in validator
            in_dir = Path(tmp) / "in"
            in_dir.mkdir()
            (in_dir / "a.txt").write_text("BP 120/80", encoding="utf-8")
            sources = UniversalIngestor().ingest_directory(in_dir)
            (out_dir / "sanitized" / "a.txt").write_text("BP 120/80", encoding="utf-8")
            write_records_jsonl(sources, out_dir)
            m = AuditMetrics(
                files=[FileReportEntry(sources[0].source_sha256, "sanitized/a.txt", "sanitized")],
                files_total=1,
                files_sanitized=1,
                files_quarantined=0,
                records_processed=1,
            )
            write_report_json(m, out_dir)

            old = os.environ.get("RAKSHA_SECRET")
            os.environ["RAKSHA_SECRET"] = "sanitized/a.txt"
            try:
                with self.assertRaises(OutputValidationError):
                    validate_serialized_output(sources, out_dir)
            finally:
                if old is None:
                    os.environ.pop("RAKSHA_SECRET", None)
                else:
                    os.environ["RAKSHA_SECRET"] = old


if __name__ == "__main__":
    unittest.main()
