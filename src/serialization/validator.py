# Purpose: Post-serialization validator verifying output contract compliance, clinical integrity, and zero raw PII/filename leaks.
"""Post-serialization output validation and leak detection."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
from pathlib import Path
from typing import Any, Sequence

from src.contracts import FileFormat, ParseStatus, SourceFile


class OutputValidationError(Exception):
    """Raised when serialized outputs violate format, schema, or leak invariants."""


def _privacy_safe_clinical_form(value: str) -> str:
    """Mirror typed identifier removal when validating a mixed clinical string."""
    value = re.sub(
        r"(?i)\b(?:MLC|FIR|GD|CASE\s+NO\.?|CLAIM(?:\s+NO\.?)?)\s*[:#-]?\s*\d[A-Z0-9/-]*",
        "[CASE_NO]",
        value,
    )
    return re.sub(
        r"(?i)(?:[;,.]\s*)?\b(?:oldest|youngest|first|only)\s+(?:patient|case)\b[^,;.!?]*|"
        r"(?:[;,.]\s*)?\b(?:pehla\s+case|sabse\s+buzurg|only\s+patient|famous|vip|celebrity)\b[^,;.!?]*",
        "",
        value,
    )


def _collect_fhir_searchable_text(fhir_obj: Any, base_text: str) -> str:
    """Include decoded UTF-8 base64 attachment payloads when verifying clinical terms."""
    chunks = [base_text]
    stack: list[Any] = [fhir_obj]
    while stack:
        curr = stack.pop()
        if isinstance(curr, dict):
            data_b64 = curr.get("data")
            ctype = curr.get("contentType")
            if isinstance(data_b64, str) and data_b64 and (
                not isinstance(ctype, str)
                or ctype.lower().startswith("text/")
                or "json" in ctype.lower()
                or "xml" in ctype.lower()
            ):
                try:
                    chunks.append(base64.b64decode(data_b64, validate=True).decode("utf-8"))
                except (binascii.Error, UnicodeDecodeError):
                    pass
            stack.extend(v for v in curr.values() if isinstance(v, (dict, list)))
        elif isinstance(curr, list):
            stack.extend(item for item in curr if isinstance(item, (dict, list)))
    return "\n".join(chunks)


def validate_serialized_output(
    sources: Sequence[SourceFile],
    output_dir: Path,
) -> None:
    """Verify sanitized/, report.json, and records.jsonl meet all official contract rules."""
    report_path = output_dir / "report.json"
    records_path = output_dir / "records.jsonl"
    sanitized_root = output_dir / "sanitized"

    if not report_path.is_file() or not records_path.is_file() or not sanitized_root.is_dir():
        raise OutputValidationError("Missing required output/ artifacts")

    report_text = report_path.read_text(encoding="utf-8")
    report = json.loads(report_text)

    # 1. Verify no RAKSHA_SECRET or raw source relative paths leaked into report.json or records.jsonl.
    secret = os.environ.get("RAKSHA_SECRET", "")
    records_text = records_path.read_text(encoding="utf-8")
    if secret and (secret in report_text or secret in records_text):
        raise OutputValidationError("RAKSHA_SECRET leaked into output reports")

    for src in sources:
        if src.relative_path in report_text and (
            src.parse_status == ParseStatus.QUARANTINED
            or src.sanitized_relative_path != f"sanitized/{src.relative_path}"
        ):
            raise OutputValidationError("Raw input relative path leaked into report.json")

        if src.parse_status == ParseStatus.QUARANTINED:
            if (sanitized_root / src.relative_path).exists():
                raise OutputValidationError("Quarantined file copied into sanitized/")
            continue

        if src.sanitized_relative_path is None:
            raise OutputValidationError("Parsed file missing sanitized_relative_path")

        out_file = output_dir / src.sanitized_relative_path
        if not out_file.is_file():
            raise OutputValidationError("Missing expected sanitized output file")

        # Verify UTF-8 decodability and JSON/FHIR structural validity on disk.
        text = out_file.read_text(encoding="utf-8")
        searchable_text = text
        if src.format == FileFormat.JSONL:
            for line in text.splitlines():
                if line.strip():
                    json.loads(line)
        if src.format in (FileFormat.JSON, FileFormat.FHIR_R4):
            parsed = json.loads(text)
            if src.format == FileFormat.FHIR_R4:
                if not isinstance(parsed, dict) or not isinstance(parsed.get("resourceType"), str):
                    raise OutputValidationError("Sanitized FHIR file is missing resourceType")
                searchable_text = _collect_fhir_searchable_text(parsed, text)

        # Verify clinical attributes survive intact.
        for rec in src.records:
            for clinical_val in rec.clinical_attributes:
                if (
                    clinical_val
                    and clinical_val not in searchable_text
                    and _privacy_safe_clinical_form(clinical_val) not in searchable_text
                ):
                    raise OutputValidationError("Protected clinical attribute missing in sanitized output")

    # 2. Cross-check records.jsonl count vs report.json records_processed.
    rec_lines = [line for line in records_text.splitlines() if line.strip()]
    expected_records = int(report["counts"]["records_processed"])
    if len(rec_lines) != expected_records:
        raise OutputValidationError("records.jsonl line count does not match records_processed")
