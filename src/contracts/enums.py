# Purpose: Shared fixed vocabularies (file formats, parse statuses, span roles, linkage verdicts, transforms).
"""Canonical enumerations shared across all RAKSHA pipeline stages."""

from __future__ import annotations

from enum import StrEnum


class FileFormat(StrEnum):
    """Supported input/output healthcare file formats."""

    CSV = "csv"
    TSV = "tsv"
    JSON = "json"
    FHIR_R4 = "fhir_r4"
    TEXT = "text"
    UNSUPPORTED = "unsupported"


class ParseStatus(StrEnum):
    """Outcome of ingesting an input file."""

    PARSED = "parsed"
    PARTIAL_QUARANTINE = "partial_quarantine"
    QUARANTINED = "quarantined"


class SpanRole(StrEnum):
    """Semantic privacy classification of a detected span."""

    DIRECT_PII = "direct_pii"
    QUASI_IDENTIFIER = "quasi_identifier"
    CLINICAL_PROTECTED = "clinical_protected"
    STAFF_OR_FACILITY = "staff_or_facility"


class LinkageVerdict(StrEnum):
    """Pairwise record-linkage judgment."""

    MATCH = "MATCH"
    NON_MATCH = "NON_MATCH"
    ABSTAIN = "ABSTAIN"


class ResolutionStatus(StrEnum):
    """Patient identity resolution status for a cluster or record."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    CONFLICT = "conflict"


class TransformType(StrEnum):
    """Privacy transformation applied during safe serialization."""

    PSEUDONYMIZE = "pseudonymize"
    REDACT = "redact"
    GENERALIZE = "generalize"
    DATE_SHIFT = "date_shift"
    SUPPRESS = "suppress"
    PRESERVE_CLINICAL = "preserve_clinical"
