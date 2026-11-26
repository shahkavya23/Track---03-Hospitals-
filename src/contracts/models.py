# Purpose: Core in-memory dataclasses (SourceFile, PatientRecord, FieldNode, DetectionSpan, etc.) and report.json schema.
"""Canonical in-memory data models shared across Members 1, 2, and 3."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .enums import (
    FileFormat,
    LinkageVerdict,
    ParseStatus,
    ResolutionStatus,
    SpanRole,
    TransformType,
)

CONTRACT_VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class FieldNode:
    """Single UTF-8 addressable unit extracted from a record for detection and serialization."""

    field_path: str
    raw_value: str
    header_key: str
    is_structured_key: bool
    value_type: str = "str"


@dataclass(slots=True)
class DetectionSpan:
    """Span identified by Member 2 inside a FieldNode value or header key."""

    record_ref: str
    field_path: str
    start: int
    end: int
    category: str
    role: SpanRole
    confidence: float
    detector_source: str
    is_header_detection: bool = False

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError("Invalid DetectionSpan character bounds")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("DetectionSpan confidence must be between 0.0 and 1.0")


@dataclass(slots=True)
class LinkageDecision:
    """Pairwise linkage decision produced by Member 3 without exporting raw PII."""

    record_ref_a: str
    record_ref_b: str
    decision: LinkageVerdict
    score: float
    evidence_categories: tuple[str, ...] = ()


@dataclass(slots=True)
class PatientCluster:
    """Resolved or unresolved patient cluster produced by Member 3."""

    cluster_ref: str
    member_record_refs: tuple[str, ...]
    resolution_status: ResolutionStatus
    pseudonym_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.resolution_status != ResolutionStatus.RESOLVED and self.pseudonym_id is not None:
            raise ValueError("Unresolved or conflicted clusters must not carry a pseudonym_id")


@dataclass(frozen=True, slots=True)
class PrivacyDecision:
    """Privacy transformation directive issued by Member 3 for safe serialization."""

    record_ref: str
    field_path: str
    start: Optional[int]
    end: Optional[int]
    transform_type: TransformType
    replacement_value: Optional[str] = None
    params: dict[str, Any] = field(default_factory=dict)
    clinical_constraints: tuple[str, ...] = ()


@dataclass(slots=True)
class PatientRecord:
    """Normalized internal healthcare record flowing from M1 -> M2 -> M3 -> M1."""

    record_ref: str
    source_ref: str
    loc: str
    original_structure: Any
    fields: list[FieldNode] = field(default_factory=list)
    field_metadata: dict[str, Any] = field(default_factory=dict)
    detections: list[DetectionSpan] = field(default_factory=list)
    extracted_patient_attributes: dict[str, list[str]] = field(default_factory=dict)
    clinical_attributes: list[str] = field(default_factory=list)
    cluster_ref: Optional[str] = None
    pseudonym_id: Optional[str] = None
    privacy_decisions: list[PrivacyDecision] = field(default_factory=list)


@dataclass(slots=True)
class SourceFile:
    """Ingested file envelope. `relative_path` is strictly internal and never exported."""

    source_ref: str
    source_sha256: str
    relative_path: str
    sanitized_relative_path: Optional[str]
    format: FileFormat
    encoding: str
    parse_status: ParseStatus
    quarantine_reason: Optional[str] = None
    records: list[PatientRecord] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FileReportEntry:
    """Official per-file entry in report.json (no source filenames)."""

    input_sha256: str
    output: Optional[str]
    status: str
    reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "input_sha256": self.input_sha256,
            "output": self.output,
            "status": self.status,
        }
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload


@dataclass(slots=True)
class AuditMetrics:
    """Official report.json telemetry and count structure."""

    files: list[FileReportEntry] = field(default_factory=list)
    files_total: int = 0
    files_sanitized: int = 0
    files_quarantined: int = 0
    records_processed: int = 0
    identifiers_detected: int = 0
    records_linked: int = 0
    records_generalized: int = 0
    records_suppressed: int = 0
    records_quarantined: int = 0
    seconds: float = 0.0
    peak_rss_mb: float = 0.0
    substitutions_by_type: dict[str, int] = field(default_factory=dict)
    applied_replacements: int = 0
    residual_scanner_late_catches: int = 0
    reredaction_iterations: int = 0
    engine_version: str = "unknown"
    policy_hash: str = "none"

    def to_report_dict(self) -> dict[str, Any]:
        """Serialize strictly into the official report.json schema."""
        return {
            "engine": {
                "version": self.engine_version,
                "policy_hash": self.policy_hash,
            },
            "files": [entry.to_dict() for entry in self.files],
            "counts": {
                "files_total": self.files_total,
                "files_sanitized": self.files_sanitized,
                "files_quarantined": self.files_quarantined,
                "records_processed": self.records_processed,
                "identifiers_detected": self.identifiers_detected,
                "records_linked": self.records_linked,
                "records_generalized": self.records_generalized,
                "records_suppressed": self.records_suppressed,
                "records_quarantined": self.records_quarantined,
            },
            "timing": {"seconds": round(self.seconds, 3)},
            "resources": {"peak_rss_mb": round(self.peak_rss_mb, 2)},
            "substitutions_by_type": dict(sorted(self.substitutions_by_type.items())),
            'applied_replacements': self.applied_replacements,
            'residual_scanner_late_catches': self.residual_scanner_late_catches,
            'reredaction_iterations': self.reredaction_iterations,
        }
