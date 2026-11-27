# Purpose: Verifies allowed extensions, enforces JSON depth limits, and separates FHIR R4 Bundles/Resources from JSON.
"""Secure format sniffing and classification for healthcare inputs."""

from __future__ import annotations

import json
import re
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
    stripped = text.lstrip('\ufeff').strip()
    if not stripped:
        raise IngestionQuarantineError("empty file")
    if stripped.startswith(('%PDF', 'PK\x03', 'GIF8')) or '\x00' in stripped:
        raise IngestionQuarantineError("unsupported format")
    if stripped.startswith('<'):
        raise IngestionQuarantineError("xml requires a supported schema")
    if stripped.startswith(('{', '[')):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            lines = [line for line in stripped.splitlines() if line.strip()]
            rows: list[Any] = []
            parsed_chars = 0
            for line in lines:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
                    parsed_chars += len(line.strip())
            content_chars = sum(len(line.strip()) for line in lines)
            if rows and parsed_chars / max(1, content_chars) >= .95:
                if not _max_json_depth(rows, max_json_depth):
                    raise IngestionQuarantineError("json nesting limit exceeded") from exc
                return FileFormat.JSONL, rows
            # A JSON-looking span inside prose is a mixed text document.  A
            # structurally JSON-only document that does not parse is corrupted.
            structural = sum(bool(re.match(r'\s*(?:[{}\[\]]|"[^"\n]+"\s*:)', line)) for line in lines)
            if rows or (len(lines) >= 2 and structural / len(lines) < .8):
                return FileFormat.TEXT, None
            raise IngestionQuarantineError("malformed or truncated json") from exc
        if not _max_json_depth(parsed, max_json_depth):
            raise IngestionQuarantineError("json nesting limit exceeded")
        if isinstance(parsed, dict) and isinstance(parsed.get('resourceType'), str):
            return FileFormat.FHIR_R4, parsed
        return FileFormat.JSON, parsed
    # A schema-like first row plus consistent logical rows distinguishes tables
    # from comma-containing prose. Filename suffix is never parser evidence.
    import csv
    import io
    sample_lines = [line for line in text.splitlines() if line.strip()]
    sample = '\n'.join(sample_lines)
    for delimiter in (',', ';', '\t', '|'):
        try:
            rows = list(csv.reader(io.StringIO(sample), delimiter=delimiter))[:30]
        except csv.Error:
            continue
        if len(rows) < 2 or len(rows[0]) < 2:
            continue
        width = len(rows[0])
        consistent = sum(abs(len(row)-width) <= 1 for row in rows)
        header = sum(bool(re.search(r'[A-Za-z\u0900-\u097f]', cell))
                     and not bool(re.search(r'\d{5}', cell)) for cell in rows[0])
        explicit_schema = any(re.search(r'(?i)patient|name|phone|dob|uhid|mrn|diagnos|regimen|^id$|^note$', cell) for cell in rows[0])
        threshold = .70 if explicit_schema else .95
        if consistent >= 2 and consistent / len(rows) >= threshold and header >= width / 2:
            return (FileFormat.TSV if delimiter == '\t' else FileFormat.CSV), None
    if PurePosixPath(relative_posix).suffix.lower() in {'.zip', '.xls', '.jpg', '.pdf', '.bin', '.lock'}:
        raise IngestionQuarantineError("unsupported format")
    return FileFormat.TEXT, None
