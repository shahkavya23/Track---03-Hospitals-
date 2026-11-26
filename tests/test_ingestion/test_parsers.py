# Purpose: Verifies CSV/TSV, JSON, FHIR R4, and policy.yaml parsing plus shifted-row and malformed-file handling.
"""Format parser tests for CSV, TSV, JSON, FHIR R4, and clinical text."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from src.contracts import FileFormat, ParseStatus
from src.ingestion import IngestionConfig, UniversalIngestor


class ParserTests(unittest.TestCase):
    def test_csv_and_tsv_shifted_rows_and_clinical_strings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_dir = Path(tmp) / "input"
            in_dir.mkdir()

            (in_dir / "reg.csv").write_text(
                "uhid,name,regimen,unknown_col\n"
                "00123,Md. Arif,1-0-1,extra\n"
                "00124,Meera,Dolo 650 BD x 5 days,ok,SHIFTED_PHONE_9876543210\n"
                "00125,Raju\n",
                encoding="utf-8",
            )
            (in_dir / "labs.tsv").write_text(
                "patient\thba1c\n"
                "Arif\tHbA1c 7.4%\n",
                encoding="utf-8",
            )
            (in_dir / "truncated.csv").write_text(
                'id,note\n1,"unterminated quote\n',
                encoding="utf-8",
            )

            sources = UniversalIngestor().ingest_directory(in_dir)
            by_rel = {s.relative_path: s for s in sources}

            reg = by_rel["reg.csv"]
            self.assertEqual(reg.parse_status, ParseStatus.PARSED)
            self.assertEqual(reg.format, FileFormat.CSV)
            self.assertEqual([r.loc for r in reg.records], ["row:0", "row:1", "row:2"])
            # Exact string preservation (no int/date coercion)
            self.assertEqual(reg.records[0].fields[0].raw_value, "00123")
            self.assertEqual(reg.records[0].fields[2].raw_value, "1-0-1")
            # Shifted overflow cell preserved for M2 scanning
            self.assertTrue(reg.records[1].field_metadata["is_shifted_row"])
            self.assertEqual(reg.records[1].fields[4].raw_value, "SHIFTED_PHONE_9876543210")
            self.assertTrue(reg.records[2].field_metadata["is_shifted_row"])

            labs = by_rel["labs.tsv"]
            self.assertEqual(labs.format, FileFormat.TSV)
            self.assertEqual(labs.records[0].fields[1].raw_value, "HbA1c 7.4%")

            trunc = by_rel["truncated.csv"]
            self.assertEqual(trunc.parse_status, ParseStatus.QUARANTINED)
            self.assertEqual(trunc.quarantine_reason, "malformed or truncated tabular file")

    def test_json_multi_record_nested_and_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_dir = Path(tmp) / "input"
            in_dir.mkdir()

            (in_dir / "visits.json").write_text(
                json.dumps(
                    {
                        "facility": "Yugaantar General",
                        "visits": [
                            {"patient": {"name": "Arif", "bp": "150/90"}},
                            {"patient": {"name": "Meera"}, "meta/key": "hidden"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (in_dir / "broken.json").write_text('{"visits": [{"name": "Arif"', encoding="utf-8")

            sources = UniversalIngestor().ingest_directory(in_dir)
            by_rel = {s.relative_path: s for s in sources}

            visits = by_rel["visits.json"]
            self.assertEqual(visits.parse_status, ParseStatus.PARSED)
            self.assertEqual(visits.format, FileFormat.JSON)
            self.assertEqual([r.loc for r in visits.records], ["/visits/0", "/visits/1"])
            paths = {f.field_path: f.raw_value for f in visits.records[1].fields}
            self.assertEqual(paths["/visits/1/meta~1key"], "hidden")
            self.assertEqual(paths["/facility"], "Yugaantar General")

            broken = by_rel["broken.json"]
            self.assertEqual(broken.parse_status, ParseStatus.QUARANTINED)
            self.assertEqual(broken.quarantine_reason, "malformed or truncated json")

    def test_fhir_r4_bundle_references_and_decoded_attachment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_dir = Path(tmp) / "input"
            in_dir.mkdir()

            attachment_b64 = base64.b64encode(
                "Patient: मोहम्मद आरिफ | Rx: Ramipril 5 mg".encode("utf-8")
            ).decode("ascii")

            bundle = {
                "resourceType": "Bundle",
                "type": "collection",
                "entry": [
                    {
                        "fullUrl": "urn:uuid:pat-1",
                        "resource": {
                            "resourceType": "Patient",
                            "id": "pat-1",
                            "name": [{"text": "Mohammad Arif"}],
                        },
                    },
                    {
                        "resource": {
                            "resourceType": "DocumentReference",
                            "subject": {"reference": "Patient/pat-1"},
                            "content": [
                                {
                                    "attachment": {
                                        "contentType": "text/plain",
                                        "data": attachment_b64,
                                    }
                                }
                            ],
                        }
                    },
                ],
            }
            (in_dir / "bundle.json").write_text(json.dumps(bundle), encoding="utf-8")
            (in_dir / "bad_fhir.json").write_text(
                json.dumps({"resourceType": "Bundle", "entry": "not-a-list"}),
                encoding="utf-8",
            )

            sources = UniversalIngestor().ingest_directory(in_dir)
            by_rel = {s.relative_path: s for s in sources}

            good = by_rel["bundle.json"]
            self.assertEqual(good.parse_status, ParseStatus.PARSED)
            self.assertEqual(good.format, FileFormat.FHIR_R4)
            self.assertEqual(good.records[0].loc, "doc")
            self.assertEqual(good.records[0].field_metadata["bundle_references"]["Patient/pat-1"], 0)
            self.assertEqual(good.records[0].field_metadata["decoded_attachment_count"], 1)
            decoded_vals = [f.raw_value for f in good.records[0].fields if "decoded_attachment" in f.field_path]
            self.assertTrue(any("Ramipril 5 mg" in v and "मोहम्मद आरिफ" in v for v in decoded_vals))

            bad = by_rel["bad_fhir.json"]
            self.assertEqual(bad.parse_status, ParseStatus.QUARANTINED)
            self.assertEqual(bad.quarantine_reason, "malformed fhir bundle")

    def test_policy_yaml_config_loads(self) -> None:
        cfg = IngestionConfig.from_policy_file(Path("config/policy.yaml"))
        self.assertEqual(cfg.max_file_bytes, 52_428_800)
        self.assertEqual(cfg.empty_file_action, "quarantine")
        self.assertIn(".json", cfg.supported_extensions)


if __name__ == "__main__":
    unittest.main()
