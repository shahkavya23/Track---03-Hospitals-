# Purpose: Verifies allowed extensions, enforces JSON depth limits, and separates FHIR R4 Bundles/Resources from JSON.
"""Secure format sniffing and classification for healthcare inputs."""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any, Optional, Sequence

from src.contracts import FileFormat

from .errors import IngestionQuarantineError

DEFAULT_SUPPORTED_EXTENSIONS: tuple[str, ...] = (".csv", ".tsv", ".json", ".txt")


def _max_json_depth(obj: Any, limit: int) -> bool:
    """Iteratively verify JSON nesting depth does not exceed `limit`."""
    stack: list[tuple[Any, int]] = [(obj, 1)]
    while stack:
        current, depth = stack.pop()
        if depth > limit:
            return False
        if isinstance(current, dict):
            for value in current.values():
                if isinstance(value, (dict, list)):
                    stack.append((value, depth + 1))
        elif isinstance(current, list):
            for item in current:
                if isinstance(item, (dict, list)):
                    stack.append((item, depth + 1))
    return True


def detect_format(
    relative_posix: str,
    text: str,
    supported_extensions: Sequence[str] = DEFAULT_SUPPORTED_EXTENSIONS,
    max_json_depth: int = 64,
) -> tuple[FileFormat, Optional[Any]]:
    """Determine verified FileFormat (and pre-parsed JSON payload if applicable)."""
    suffix = PurePosixPath(relative_posix).suffix.lower()
    if suffix not in supported_extensions:
        raise IngestionQuarantineError("unsupported format")

    if suffix == ".csv":
        return FileFormat.CSV, None
    if suffix == ".tsv":
        return FileFormat.TSV, None
    if suffix == ".txt":
        if not text.strip():
            raise IngestionQuarantineError("empty file")
        return FileFormat.TEXT, None

    # .json -> distinguish FHIR R4 vs generic JSON
    if not text.strip():
        raise IngestionQuarantineError("empty file")

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IngestionQuarantineError("malformed or truncated json") from exc

    if not _max_json_depth(parsed, max_json_depth):
        raise IngestionQuarantineError("json nesting limit exceeded")

    if isinstance(parsed, dict) and isinstance(parsed.get("resourceType"), str) and parsed["resourceType"].strip():
        return FileFormat.FHIR_R4, parsed

    return FileFormat.JSON, parsed
