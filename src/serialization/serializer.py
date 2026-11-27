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
from .publish_gate import MemoryTarget, reredact_candidate, reredact_registry, validate_candidate
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
                    FileFormat.JSONL: write_json_source,
                    FileFormat.TEXT: write_text_source,
                }[src.format]
                writer(src, candidate)
                late = reredact_candidate(candidate.value, max_iterations=3)
                candidate.value = late.value
                candidate.value, registry_late = reredact_registry(src, candidate.value)
                if src.records:
                    src.records[0].field_metadata['late_redaction_replacements'] = late.replacements + registry_late
                    src.records[0].field_metadata['late_redaction_iterations'] = late.iterations
                    src.records[0].field_metadata['late_redaction_categories'] = late.late_categories
                if late.remaining:
                    raise ValueError('residual_after_reredact')
                validate_candidate(src, candidate.value)
                # Only verified sanitized bytes reach disk. Same-directory rename
                # is atomic; the unverified rendering never leaves memory.
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                                                 dir=target_path.parent, delete=False) as handle:
                    staging = Path(handle.name)
                    handle.write(candidate.value)
                os.replace(staging, target_path)
            except Exception as exc:
                src.parse_status = ParseStatus.QUARANTINED
                reason_map = {
                    'independent residual identifiers': 'residual_after_reredact',
                    'residual identifiers': 'registry_residual_after_reredact',
                    'clinical integrity': 'clinical_integrity_failure',
                    'unsafe output': 'unsafe_output',
                    'residual_after_reredact': 'residual_after_reredact',
                }
                src.quarantine_reason = reason_map.get(str(exc), 'serialization_failure') if isinstance(exc, ValueError) else 'serialization_failure'
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
        metrics.applied_replacements = sum(
            len(record.field_metadata.get('applied_events', {})) +
            int(record.field_metadata.get('late_redaction_replacements', 0))
            for source in sources if source.parse_status == ParseStatus.PARSED
            for record in source.records
        )
        metrics.residual_scanner_late_catches = sum(
            int(record.field_metadata.get('late_redaction_replacements', 0))
            for source in sources for record in source.records
        )
        metrics.reredaction_iterations = max((
            int(record.field_metadata.get('late_redaction_iterations', 0))
            for source in sources for record in source.records
        ), default=0)

        write_records_jsonl(sources, output_dir)
        write_report_json(metrics, output_dir)

        if self.validate_output:
            validate_serialized_output(sources, output_dir)

        return metrics
