"""Unified document-processing engine, versioning, cache keys, and trace counters."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Sequence

from src.clinical import ClinicalIntegrityGuard
from src.contracts import (
    ClinicalGuard,
    PIIDetector,
    ParseStatus,
    PatientCluster,
    PatientRecord,
    PrivacyDecision,
    PrivacyEngine,
    SourceFile,
    SpanRole,
    TransformType,
)
from src.detection import MultilingualPIIDetector
from src.privacy import AdaptivePrivacyEngine
from src.security.independent_scan import _searchable_with_map, scan_findings


_REPO_ROOT = Path(__file__).resolve().parents[1]


def repo_head_version() -> str:
    """Return the current git HEAD commit hash (or 'unknown' outside a git repo)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        return out or "unknown"
    except Exception:
        return "unknown"


ENGINE_VERSION: str = repo_head_version()


def compute_policy_hash(policy_path: Path | None) -> str:
    """Return SHA-256 hex digest of the active policy file, or 'none' if absent."""
    if policy_path is None or not policy_path.exists():
        return "none"
    return hashlib.sha256(policy_path.read_bytes()).hexdigest()[:16]


def secret_fingerprint(secret_key: bytes) -> str:
    """Return an HMAC-derived fingerprint of the secret key (never the secret itself)."""
    return hmac.new(secret_key, b"raksha:secret-fingerprint", hashlib.sha256).hexdigest()[:16]


def compute_cache_key(
    engine_version: str,
    policy_hash: str,
    secret_fp: str,
    input_sha256: str,
) -> str:
    """Compute a cache key that invalidates on any code, policy, secret, or input change."""
    payload = f"{engine_version}|{policy_hash}|{secret_fp}|{input_sha256}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(slots=True)
class EngineTrace:
    """Per-module execution counters (counts only; never stores raw PII)."""

    views_built: int = 0
    ocr_substitutions: int = 0
    spelled_number_runs: int = 0
    blocks_by_type: Counter[str] = field(default_factory=Counter)
    candidates_by_type: Counter[str] = field(default_factory=Counter)
    ledger_decisions_by_reason: Counter[str] = field(default_factory=Counter)
    dates_shifted: int = 0
    weekdays_recomputed: int = 0
    ages_banded: int = 0
    verify_hits: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "views_built": self.views_built,
            "ocr_substitutions": self.ocr_substitutions,
            "spelled_number_runs": self.spelled_number_runs,
            "blocks_by_type": dict(sorted(self.blocks_by_type.items())),
            "candidates_by_type": dict(sorted(self.candidates_by_type.items())),
            "ledger_decisions_by_reason": dict(sorted(self.ledger_decisions_by_reason.items())),
            "dates_shifted": self.dates_shifted,
            "weekdays_recomputed": self.weekdays_recomputed,
            "ages_banded": self.ages_banded,
            "verify_hits": self.verify_hits,
        }


@dataclass(slots=True)
class EngineContext:
    """Runtime context shared by CLI and UI API calls to process_document."""

    secret_key: bytes
    detector: PIIDetector
    clinical_guard: ClinicalGuard
    privacy_engine: PrivacyEngine
    policy_path: Path | None = None
    policy_hash: str = "none"
    engine_version: str = ENGINE_VERSION
    secret_fp: str = ""
    trace_enabled: bool = False
    trace: EngineTrace = field(default_factory=EngineTrace)
    cache: dict[str, list[PrivacyDecision]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.secret_fp:
            self.secret_fp = secret_fingerprint(self.secret_key)
        if self.policy_hash == "none" and self.policy_path is not None:
            self.policy_hash = compute_policy_hash(self.policy_path)
        if not self.trace_enabled:
            self.trace_enabled = os.environ.get("ENGINE_TRACE", "").strip() in {"1", "true", "TRUE", "yes"}


def _count_views_and_ocr(text: str, trace: EngineTrace) -> None:
    if not text:
        return
    trace.views_built += 1
    folded, _ = _searchable_with_map(text)
    if folded != text:
        trace.ocr_substitutions += sum(
            1 for a, b in zip(text, folded) if a != b
        )
    for m in re.finditer(r"(?i)\b(?:zero|one|two|three|four|five|six|seven|eight|nine|oh|ek|do|teen|char|paanch|chhe|saat|aath|nau)\b(?:[\s,.-]+(?:zero|one|two|three|four|five|six|seven|eight|nine|oh|\d+)){4,}", text):
        trace.spelled_number_runs += 1
    for f in scan_findings(text):
        trace.verify_hits += 1


def detect_document(udm_doc: SourceFile, ctx: EngineContext) -> int:
    """Run detection + clinical guard on all records of a SourceFile."""
    if udm_doc.parse_status != ParseStatus.PARSED:
        return 0
    detected = 0
    fmt_key = str(udm_doc.format.value) if hasattr(udm_doc.format, "value") else str(udm_doc.format)
    for record in udm_doc.records:
        record.field_metadata["record_namespace"] = udm_doc.source_sha256
        record.field_metadata["cache_key"] = compute_cache_key(
            ctx.engine_version, ctx.policy_hash, ctx.secret_fp, udm_doc.source_sha256
        )
        raw_spans = ctx.detector.analyze_record(record)
        protected_spans, clinical_attrs = ctx.clinical_guard.protect_clinical(record, raw_spans)
        record.detections = list(protected_spans)
        record.clinical_attributes = list(clinical_attrs)
        ctx.trace.blocks_by_type[fmt_key] += len(record.fields)
        for node in record.fields:
            _count_views_and_ocr(node.raw_value, ctx.trace)
        for span in record.detections:
            if span.role != SpanRole.CLINICAL_PROTECTED:
                detected += 1
                ctx.trace.candidates_by_type[span.category] += 1
    return detected


def process_batch(
    sources: Sequence[SourceFile],
    ctx: EngineContext,
    *,
    clusters: Sequence[PatientCluster] = (),
    already_detected: bool = False,
) -> list[PrivacyDecision]:
    """Run unified engine processing across one or more SourceFiles."""
    parsed = [s for s in sources if s.parse_status == ParseStatus.PARSED]
    if not parsed:
        return []
    if not already_detected:
        for doc in parsed:
            detect_document(doc, ctx)

    all_records = [rec for doc in parsed for rec in doc.records]
    decisions = ctx.privacy_engine.transform(all_records, clusters, ctx.secret_key)
    decision_by_record: dict[str, list[PrivacyDecision]] = {}
    for decision in decisions:
        decision_by_record.setdefault(decision.record_ref, []).append(decision)
        reason = str(decision.transform_type.value) if hasattr(decision.transform_type, "value") else str(decision.transform_type)
        ctx.trace.ledger_decisions_by_reason[reason] += 1
        if decision.transform_type == TransformType.DATE_SHIFT:
            ctx.trace.dates_shifted += 1
            if decision.replacement_value and re.match(r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)", decision.replacement_value):
                ctx.trace.weekdays_recomputed += 1
        elif decision.transform_type == TransformType.GENERALIZE and decision.replacement_value and (
            re.fullmatch(r"\d+-\d+", decision.replacement_value) or decision.replacement_value in {"<1", "90+"}
        ):
            ctx.trace.ages_banded += 1

    for doc in parsed:
        cache_key = compute_cache_key(
            ctx.engine_version, ctx.policy_hash, ctx.secret_fp, doc.source_sha256
        )
        doc_decisions: list[PrivacyDecision] = []
        for record in doc.records:
            if record.record_ref in decision_by_record:
                record.privacy_decisions = decision_by_record[record.record_ref]
                doc_decisions.extend(record.privacy_decisions)
            record.field_metadata["cache_key"] = cache_key
        ctx.cache[cache_key] = doc_decisions
    return decisions


def process_document(
    udm_doc: SourceFile,
    ctx: EngineContext,
    *,
    clusters: Sequence[PatientCluster] = (),
    already_detected: bool = False,
) -> list[PrivacyDecision]:
    """Single unified entry function for TEXT, CSV/TSV, JSON, FHIR, and UI API."""
    return process_batch([udm_doc], ctx, clusters=clusters, already_detected=already_detected)


def emit_trace(ctx: EngineContext) -> None:
    """Print per-module counters (counts only, no content) when ENGINE_TRACE=1."""
    if ctx.trace_enabled:
        print(f"ENGINE_TRACE {json.dumps(ctx.trace.to_dict(), sort_keys=True)}", file=sys.stderr, flush=True)
