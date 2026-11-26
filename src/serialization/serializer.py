# Purpose: SafeOutputSerializer implementing SafeSerializer to write sanitized/, records.jsonl, report.json, and validate outputs.
"""Safe output serialization orchestrator (Member 1)."""

from __future__ import annotations

from pathlib import Path
from collections import Counter
import re
import os
import tempfile
from typing import Sequence

from src.contracts import AuditMetrics, FileFormat, ParseStatus, SourceFile
from src.reporting import write_records_jsonl, write_report_json

from .validator import validate_serialized_output
from .publish_gate import MemoryTarget, validate_candidate
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

            candidate = MemoryTarget()
            staging = None
            try:
                writer = {
                    FileFormat.CSV: write_tabular_source, FileFormat.TSV: write_tabular_source,
                    FileFormat.JSON: write_json_source, FileFormat.FHIR_R4: write_fhir_source,
                    FileFormat.TEXT: write_text_source,
                }[src.format]
                writer(src, candidate)
                validate_candidate(src, candidate.value)
                # Only verified sanitized bytes reach disk. Same-directory rename
                # is atomic; the unverified rendering never leaves memory.
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                                 dir=target_path.parent, delete=False) as handle:
                    staging = Path(handle.name)
                    handle.write(candidate.value)
                os.replace(staging, target_path)
            except Exception:
                src.parse_status = ParseStatus.QUARANTINED
                src.quarantine_reason = 'output verification failed'
                src.sanitized_relative_path = None
                target_path.unlink(missing_ok=True)
                metrics.files[idx] = type(metrics.files[idx])(
                    input_sha256=src.source_sha256, output=None, status='quarantined',
                    reason=src.quarantine_reason)
                metrics.files_sanitized -= 1
                metrics.files_quarantined += 1
                count = sum(not r.field_metadata.get('is_footer_row') and
                            not r.field_metadata.get('is_empty_row') for r in src.records)
                metrics.records_processed -= count
                metrics.records_linked -= sum(r.pseudonym_id is not None for r in src.records)
                metrics.records_generalized = max(0, metrics.records_generalized - count)
                metrics.records_quarantined += count
            finally:
                if staging is not None:
                    staging.unlink(missing_ok=True)

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
