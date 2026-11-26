"""PII-safe stage/count diagnostic for a single local input file."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from src.contracts import SpanRole
from src.pipeline import RakshaPipeline
from src.security.independent_scan import scan
from src.serialization.publish_gate import MemoryTarget, residual_hits, reredact_candidate, reredact_registry, validate_candidate
from src.serialization.writers import write_text_source


def main(path: Path) -> None:
    os.environ.setdefault("RAKSHA_SECRET", "local-diagnostic-key")
    stages: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        input_dir = root / "input"
        input_dir.mkdir()
        shutil.copyfile(path, input_dir / path.name)
        pipeline = RakshaPipeline()
        try:
            sources = pipeline.ingestor.ingest_directory(input_dir)
            stages.append({"stage": "ingest", "raised": False})
        except Exception:
            print(json.dumps({"stage": "ingest", "raised": True}))
            return
        source = sources[0]
        details: dict[str, object] = {
            "parser": source.format.value,
            "parse_status": source.parse_status.value,
            "records": len(source.records),
        }
        if not source.records:
            details["stages"] = stages
            print(json.dumps(details, sort_keys=True))
            return
        records = source.records
        mentions = 0
        try:
            for record in records:
                raw = pipeline.detector.analyze_record(record)
                protected, clinical = pipeline.clinical_guard.protect_clinical(record, raw)
                record.detections = list(protected)
                record.clinical_attributes = list(clinical)
                mentions += sum(s.role != SpanRole.CLINICAL_PROTECTED for s in protected)
            stages.append({"stage": "detect_and_protect", "raised": False})
        except Exception:
            stages.append({"stage": "detect_and_protect", "raised": True})
        try:
            _, clusters = pipeline.linker.link_records(records)
            stages.append({"stage": "link", "raised": False})
        except Exception:
            stages.append({"stage": "link", "raised": True})
            clusters = []
        try:
            decisions = pipeline.privacy_engine.transform(records, clusters, b"local-diagnostic-key")
            by_record: dict[str, list] = {}
            for decision in decisions:
                by_record.setdefault(decision.record_ref, []).append(decision)
            for record in records:
                record.privacy_decisions = by_record.get(record.record_ref, [])
            stages.append({"stage": "privacy", "raised": False})
        except Exception:
            decisions = []
            stages.append({"stage": "privacy", "raised": True})
        candidate = MemoryTarget()
        try:
            write_text_source(source, candidate)
            stages.append({"stage": "render", "raised": False})
        except Exception:
            stages.append({"stage": "render", "raised": True})
        applied = sum(len(r.field_metadata.get("applied_events", {})) for r in records)
        independent = scan(candidate.value)
        registry_hits = residual_hits(source, candidate.value)
        late = reredact_candidate(candidate.value)
        late_value, registry_late = reredact_registry(source, late.value)
        missing_clinical = sum(
            bool(value) and value not in late_value
            for record in records for value in record.clinical_attributes
        )
        try:
            validate_candidate(source, candidate.value)
            gate_reason = None
        except ValueError as exc:
            gate_reason = str(exc)
        details.update({
            "mentions_pass_1": mentions,
            "decisions_pass_3": len(decisions),
            "rewrites_applied": applied,
            "residual_categories": independent,
            "registry_residual_count": registry_hits,
            "late_categories": late.late_categories,
            "late_replacements": late.replacements + registry_late,
            "missing_clinical_after_late": missing_clinical,
            "gate_reason": gate_reason,
            "stages": stages,
            "reredact_implemented": False,
        })
        print(json.dumps(details, sort_keys=True))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
