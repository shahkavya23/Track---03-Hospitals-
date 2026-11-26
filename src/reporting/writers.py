# Purpose: Writes official report.json and records.jsonl outputs with strict schema and count verification.
"""Official report.json and records.jsonl writers (Member 1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from src.contracts import AuditMetrics, ParseStatus, SourceFile


def write_records_jsonl(sources: Sequence[SourceFile], output_dir: Path) -> Path:
    """Write one JSON line per parsed PatientRecord: {file, loc, patient}."""
    target = output_dir / "records.jsonl"
    lines: list[str] = []

    for src in sources:
        if src.parse_status != ParseStatus.PARSED or src.sanitized_relative_path is None:
            continue
        for record in src.records:
            if record.field_metadata.get("is_empty_row") or record.field_metadata.get("is_footer_row"):
                continue
            entry = {
                "file": src.sanitized_relative_path,
                "loc": record.loc,
                "patient": record.pseudonym_id,
            }
            lines.append(json.dumps(entry, ensure_ascii=False))

    content = ("\n".join(lines) + "\n") if lines else ""
    target.write_text(content, encoding="utf-8")
    return target


def write_report_json(metrics: AuditMetrics, output_dir: Path) -> Path:
    """Validate audit totals and write report.json in UTF-8."""
    if metrics.files_total != metrics.files_sanitized + metrics.files_quarantined:
        raise ValueError("AuditMetrics file count mismatch: total != sanitized + quarantined")
    if len(metrics.files) != metrics.files_total:
        raise ValueError("AuditMetrics files list length does not match files_total")

    payload = metrics.to_report_dict()
    target = output_dir / "report.json"
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target
