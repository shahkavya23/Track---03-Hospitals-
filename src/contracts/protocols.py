# Purpose: Typed Python Protocol interfaces decoupling Member 1, Member 2, and Member 3 pipeline stages.
"""Stage protocols decoupling Member 1, Member 2, and Member 3 modules."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence

from .models import (
    AuditMetrics,
    DetectionSpan,
    LinkageDecision,
    PatientCluster,
    PatientRecord,
    PrivacyDecision,
    SourceFile,
)


class Ingestor(Protocol):
    """Member 1: Discover, validate, decode, and parse input files into SourceFiles."""

    def ingest_directory(self, input_dir: Path) -> list[SourceFile]: ...


class PIIDetector(Protocol):
    """Member 2: Detect multilingual PII, quasi-identifiers, and clinical entities."""

    def analyze_record(self, record: PatientRecord) -> list[DetectionSpan]: ...


class ClinicalGuard(Protocol):
    """Member 2: Protect medical terms, doses, vitals, and lab values from redaction."""

    def protect_clinical(
        self, record: PatientRecord, spans: Sequence[DetectionSpan]
    ) -> tuple[list[DetectionSpan], list[str]]: ...


class LinkageEngine(Protocol):
    """Member 3: Cluster patient records across languages and hospitals without false merges."""

    def link_records(
        self, records: Sequence[PatientRecord]
    ) -> tuple[list[LinkageDecision], list[PatientCluster]]: ...


class PrivacyEngine(Protocol):
    """Member 3: Issue keyed-HMAC pseudonyms and quasi-identifier PrivacyDecisions."""

    def transform(
        self,
        records: Sequence[PatientRecord],
        clusters: Sequence[PatientCluster],
        secret_key: bytes,
    ) -> list[PrivacyDecision]: ...


class SafeSerializer(Protocol):
    """Member 1: Emit sanitized/, records.jsonl, and report.json with zero leaks."""

    def serialize_all(
        self,
        sources: Sequence[SourceFile],
        output_dir: Path,
        metrics: AuditMetrics,
    ) -> AuditMetrics: ...
