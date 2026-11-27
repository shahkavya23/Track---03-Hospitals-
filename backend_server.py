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
from src.engine import ENGINE_VERSION, compute_policy_hash, repo_head_version
from src.pipeline import RakshaPipeline
from src.privacy.engine import AdaptivePrivacyEngine
from src.serialization import SafeOutputSerializer
from src.security.independent_scan import scan
from src.ingestion.encoding import decode_bytes_to_utf8
from src.ingestion.format_detect import detect_format


def output_verification():
    counts = {}
    root = OUTPUT_DIR / 'sanitized'
    for path in sorted(root.rglob('*')) if root.exists() else []:
        if path.is_file():
            for category, count in scan(path.read_text(encoding='utf-8')).items():
                counts[category] = counts.get(category, 0) + count
    hits = sum(counts.values())
    # Full invariant certification is not implemented. Never equate a clean
    # regex scan with proof of all privacy and clinical invariants.
    return {'hits': hits, 'categories': counts, 'invariants_complete': False,
            'verified': False, 'export_allowed': False}

HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8000"))

# Working directory for the UI session
UI_WORKSPACE = Path(".raksha_ui_workspace")
INPUT_DIR = UI_WORKSPACE / "input"
OUTPUT_DIR = UI_WORKSPACE / "output"

# Ensure environment secret is set
if "RAKSHA_SECRET" not in os.environ or not os.environ["RAKSHA_SECRET"].strip():
    os.environ["RAKSHA_SECRET"] = "RAKSHA-HACKATHON-DEAN-KEY-2026-STABLE"



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
    def log_message(self, format, *args):
        # URLs can contain uploaded filenames and patient names.
        return
    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
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

    def do_HEAD(self) -> None:
        """Respond to Render's availability probe without a response body."""
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", "0")
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        ensure_workspace()

        if path == "/api/status":
            secret = os.environ.get("RAKSHA_SECRET", "")
            head = repo_head_version()
            policy_path = Path(__file__).parent / "config/policy.yaml"
            self._send_json(
                200,
                {
                    "status": "ready",
                    "version": "1.0.0",
                    "engine_version": ENGINE_VERSION,
                    "repo_head": head,
                    "engine_outdated": bool(head != "unknown" and ENGINE_VERSION != head),
                    "policy_hash": compute_policy_hash(policy_path),
                    "secret_set": bool(secret),
                    "secret_hint": 'configured' if secret else 'missing',
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
                            decoded = decode_bytes_to_utf8(p.read_bytes()).text
                            fmt = str(detect_format(p.name, decoded)[0])
                            preview = decoded[:300]
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
            head = repo_head_version()
            self._send_json(
                200,
                {
                    "report": report,
                    "records": records,
                    "engine": report.get("engine", {"version": ENGINE_VERSION, "policy_hash": "none"}),
                    "engine_outdated": bool(head != "unknown" and ENGINE_VERSION != head),
                    "verification": output_verification(),
                },
            )
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
            try:
                orig_text = original_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                orig_text = f"[Binary data: {original_path.stat().st_size} bytes]"

            san_text = None
            status = "sanitized"
            if sanitized_path.exists():
                try:
                    san_text = sanitized_path.read_text(encoding="utf-8", errors="replace")
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
                    'verification': output_verification(),
                },
            )
            return

        if path == "/api/download-zip":
            if not output_verification()['export_allowed']:
                self._send_json(409, {'error': 'Export blocked: independent verification is incomplete or leaks were detected.',
                                      'verification': output_verification()})
                return
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
                    'verification': output_verification(),
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
                if not target.resolve().is_relative_to(INPUT_DIR.resolve()):
                    self._send_json(400, {'error': 'Invalid upload path'})
                    return
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

            pipeline = RakshaPipeline(policy_path=Path(__file__).parent / 'config/policy.yaml')

            start_t = time.perf_counter()
            try:
                metrics = pipeline.run(input_dir=INPUT_DIR, output_dir=OUTPUT_DIR)
            except Exception:
                self._send_json(500, {'error': 'Pipeline failed; output is unverified.'})
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

            head = repo_head_version()
            self._send_json(
                200,
                {
                    "success": True,
                    "engine": report.get("engine", {"version": ENGINE_VERSION, "policy_hash": "none"}),
                    "engine_outdated": bool(head != "unknown" and ENGINE_VERSION != head),
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
                    'verification': output_verification(),
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
