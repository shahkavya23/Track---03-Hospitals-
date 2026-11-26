# Purpose: Orchestrates M1 ingestion -> M2 detection/clinical guard -> M3 linkage/privacy -> M1 serialization and telemetry.
"""End-to-end RAKSHA pipeline orchestration (Member 1)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

import psutil

from src.contracts import (
    AuditMetrics,
    ClinicalGuard,
    FileReportEntry,
    Ingestor,
    LinkageEngine,
    PIIDetector,
    ParseStatus,
    PatientRecord,
    PrivacyEngine,
    SafeSerializer,
    SourceFile,
    SpanRole,
    TransformType,
)
from src.ingestion import IngestionConfig, UniversalIngestor
from src.clinical import ClinicalIntegrityGuard
from src.detection import MultilingualPIIDetector
from src.linkage.engine import ConservativeLinkageEngine
from src.privacy import AdaptivePrivacyEngine
from src.serialization import SafeOutputSerializer


def read_secret_key() -> bytes:
    """Read RAKSHA_SECRET from the environment and fail closed if missing."""
    raw = os.environ.get("RAKSHA_SECRET", "")
    if not raw:
        raise RuntimeError("RAKSHA_SECRET environment variable must be set and non-empty.")
    return raw.encode("utf-8")


def _peak_rss_mb() -> float:
    process = psutil.Process()
    mem = process.memory_info()
    peak = getattr(mem, "peak_wset", mem.rss)
    return float(peak) / (1024.0 * 1024.0)


class RakshaPipeline:
    """Coordinates M1 ingestion -> M2 detection/clinical -> M3 linkage/privacy -> M1 serialization."""

    def __init__(
        self,
        ingestor: Optional[Ingestor] = None,
        detector: Optional[PIIDetector] = None,
        clinical_guard: Optional[ClinicalGuard] = None,
        linker: Optional[LinkageEngine] = None,
        privacy_engine: Optional[PrivacyEngine] = None,
        serializer: Optional[SafeSerializer] = None,
        policy_path: Optional[Path] = None,
    ) -> None:
        if ingestor is not None:
            self.ingestor = ingestor
        else:
            cfg = (
                IngestionConfig.from_policy_file(policy_path)
                if policy_path and policy_path.exists()
                else IngestionConfig()
            )
            self.ingestor = UniversalIngestor(cfg)

        default_guard = ClinicalIntegrityGuard()
        self.clinical_guard = clinical_guard if clinical_guard is not None else default_guard
        self.detector = (
            detector
            if detector is not None
            else MultilingualPIIDetector(default_guard)
        )
        self.linker = linker if linker is not None else ConservativeLinkageEngine()
        self.privacy_engine = (
            privacy_engine if privacy_engine is not None else AdaptivePrivacyEngine()
        )
        self.serializer = serializer if serializer is not None else SafeOutputSerializer()

    def run(self, input_dir: Path, output_dir: Path) -> AuditMetrics:
        """Execute the full privacy firewall pipeline safely."""
        start_ts = time.perf_counter()
        secret_key = read_secret_key()

        missing = [
            name
            for name, stage in (
                ("detector", self.detector),
                ("clinical_guard", self.clinical_guard),
                ("linker", self.linker),
                ("privacy_engine", self.privacy_engine),
                ("serializer", self.serializer),
            )
            if stage is None
        ]
        if missing:
            raise NotImplementedError(
                f"Pipeline stages not yet integrated: {', '.join(missing)}"
            )

        assert self.detector is not None
        assert self.clinical_guard is not None
        assert self.linker is not None
        assert self.privacy_engine is not None
        assert self.serializer is not None

        sources: list[SourceFile] = self.ingestor.ingest_directory(input_dir)
        all_records: list[PatientRecord] = [
            record for source in sources for record in source.records
        ]

        identifiers_detected = 0
        for record in all_records:
            raw_spans = self.detector.analyze_record(record)
            protected_spans, clinical_attrs = self.clinical_guard.protect_clinical(
                record, raw_spans
            )
            record.detections = list(protected_spans)
            record.clinical_attributes = list(clinical_attrs)
            identifiers_detected += sum(
                1 for span in record.detections if span.role != SpanRole.CLINICAL_PROTECTED
            )

        _, clusters = self.linker.link_records(all_records)
        decisions = self.privacy_engine.transform(all_records, clusters, secret_key)

        decision_by_record: dict[str, list] = {}
        for decision in decisions:
            decision_by_record.setdefault(decision.record_ref, []).append(decision)
        for record in all_records:
            if record.record_ref in decision_by_record:
                record.privacy_decisions = decision_by_record[record.record_ref]

        files_sanitized = sum(1 for src in sources if src.parse_status == ParseStatus.PARSED)
        files_quarantined = sum(1 for src in sources if src.parse_status == ParseStatus.QUARANTINED)

        metrics = AuditMetrics(
            files=[
                FileReportEntry(
                    input_sha256=src.source_sha256,
                    output=src.sanitized_relative_path if src.parse_status == ParseStatus.PARSED else None,
                    status="sanitized" if src.parse_status == ParseStatus.PARSED else "quarantined",
                    reason=src.quarantine_reason,
                )
                for src in sources
            ],
            files_total=len(sources),
            files_sanitized=files_sanitized,
            files_quarantined=files_quarantined,
            records_processed=len(all_records),
            identifiers_detected=identifiers_detected,
            records_linked=sum(1 for rec in all_records if rec.pseudonym_id is not None),
            records_generalized=sum(
                1
                for rec in all_records
                if any(
                    d.transform_type in (TransformType.GENERALIZE, TransformType.DATE_SHIFT)
                    for d in rec.privacy_decisions
                )
            ),
            records_suppressed=sum(
                1
                for rec in all_records
                if any(d.transform_type == TransformType.SUPPRESS for d in rec.privacy_decisions)
            ),
            records_quarantined=0,
            seconds=time.perf_counter() - start_ts,
            peak_rss_mb=_peak_rss_mb(),
        )

        metrics = self.serializer.serialize_all(sources, output_dir, metrics)
        metrics.seconds = time.perf_counter() - start_ts
        metrics.peak_rss_mb = _peak_rss_mb()
        return metrics
