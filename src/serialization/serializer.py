# Purpose: SafeOutputSerializer implementing SafeSerializer to write sanitized/, records.jsonl, report.json, and validate outputs.
"""Safe output serialization orchestrator (Member 1)."""

from __future__ import annotations

from pathlib import Path
from collections import Counter
import re
from typing import Sequence

from src.contracts import AuditMetrics, FileFormat, ParseStatus, SourceFile
from src.reporting import write_records_jsonl, write_report_json

from .validator import validate_serialized_output
from .writers import (
    resolve_safe_output_path,
    write_fhir_source,
    write_json_source,
    write_tabular_source,
    write_text_source,
)


class SafeOutputSerializer:
    """Writes format-preserved UTF-8 outputs, records.jsonl, and report.json safely."""

    def __init__(self, validate_output: bool = True) -> None:
        self.validate_output = validate_output

    def serialize_all(
        self,
        sources: Sequence[SourceFile],
        output_dir: Path,
        metrics: AuditMetrics,
    ) -> AuditMetrics:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "sanitized").mkdir(parents=True, exist_ok=True)

        for idx, src in enumerate(sources):
            if src.parse_status != ParseStatus.PARSED:
                continue

            target_path = resolve_safe_output_path(src, output_dir)
            # Keep FileReportEntry.output synced if filename-PII triggered a safe rename.
            if idx < len(metrics.files):
                metrics.files[idx] = type(metrics.files[idx])(
                    input_sha256=metrics.files[idx].input_sha256,
                    output=src.sanitized_relative_path,
                    status=metrics.files[idx].status,
                    reason=metrics.files[idx].reason,
                )

            if src.format in (FileFormat.CSV, FileFormat.TSV):
                write_tabular_source(src, target_path)
            elif src.format == FileFormat.JSON:
                write_json_source(src, target_path)
            elif src.format == FileFormat.FHIR_R4:
                write_fhir_source(src, target_path)
            elif src.format == FileFormat.TEXT:
                write_text_source(src, target_path)
            else:
                raise ValueError(f"Unsupported format for serialization: {src.format}")

        substitution_counts: Counter[str] = Counter()
        for src in sources:
            if src.parse_status != ParseStatus.PARSED or not src.sanitized_relative_path:
                continue
            rendered = (output_dir / src.sanitized_relative_path).read_text(encoding="utf-8")
            substitution_counts.update(re.findall(r"\[([A-Z][A-Z_]+)\]", rendered))
            substitution_counts["PSN"] += len(re.findall(r"\bPSN-[A-Z2-7]+\b", rendered))
            substitution_counts["REC"] += len(re.findall(r"\bREC-[A-Z2-7]+\b", rendered))
        metrics.substitutions_by_type = {
            key: count for key, count in substitution_counts.items() if count
        }

        write_records_jsonl(sources, output_dir)
        write_report_json(metrics, output_dir)

        if self.validate_output:
            validate_serialized_output(sources, output_dir)

        return metrics
