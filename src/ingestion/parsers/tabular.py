# Purpose: Parses CSV/TSV into 0-indexed `row:N` records while catching truncated quotes and preserving shifted columns.
"""CSV and TSV parser handling shifted columns, unknown headers, and truncated quotes."""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from typing import Callable, Sequence

from src.contracts import FieldNode, FileFormat, PatientRecord

from ..errors import IngestionQuarantineError


def _has_unterminated_quotes(text: str, delimiter: str) -> bool:
    """Detect truncated CSV/TSV files ending inside an unclosed quoted field."""
    in_quotes = False
    at_field_start = True
    idx = 0
    length = len(text)

    while idx < length:
        ch = text[idx]
        if in_quotes:
            if ch == '"':
                if idx + 1 < length and text[idx + 1] == '"':
                    idx += 2
                    continue
                in_quotes = False
            idx += 1
            continue

        if at_field_start and ch == '"':
            in_quotes = True
            at_field_start = False
        elif ch == delimiter or ch == "\n":
            at_field_start = True
        else:
            at_field_start = False
        idx += 1

    return in_quotes


def _detect_csv_delimiter(text: str, allowed_delimiters: Sequence[str]) -> str:
    """Choose delimiter for CSV files without altering TSV strict tab semantics."""
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    if not first_line:
        return ","

    best_delim = ","
    best_count = first_line.count(",")
    if best_count > 0:
        return best_delim

    for candidate in allowed_delimiters:
        count = first_line.count(candidate)
        if count > best_count:
            best_delim = candidate
            best_count = count
    return best_delim


def parse_tabular_document(
    text: str,
    source_ref: str,
    file_format: FileFormat,
    next_record_ref: Callable[[], str],
    allowed_delimiters: Sequence[str] = (",", ";", "|"),
) -> list[PatientRecord]:
    """Parse CSV or TSV into normalized PatientRecords with 0-indexed `row:N` locs."""
    if not text.strip():
        raise IngestionQuarantineError("empty file")

    delimiter = "\t" if file_format == FileFormat.TSV else _detect_csv_delimiter(text, allowed_delimiters)

    if _has_unterminated_quotes(text, delimiter):
        raise IngestionQuarantineError("malformed or truncated tabular file")

    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, quotechar='"'))
    except csv.Error as exc:
        raise IngestionQuarantineError("malformed or truncated tabular file") from exc

    # Preserve logical empty rows; only physical blank lines parsed as [] are ignorable.
    non_empty_rows = [row for row in rows if row]
    if not non_empty_rows:
        raise IngestionQuarantineError("empty file")

    headers = non_empty_rows[0]
    header_counts = Counter(headers)
    duplicate_headers = sorted(name for name, cnt in header_counts.items() if cnt > 1)
    has_blank_headers = any(not col.strip() for col in headers)

    records: list[PatientRecord] = []
    for row_idx, row in enumerate(non_empty_rows[1:]):
        original_column_count = len(row)
        # Recover a common real-world CSV defect: an unquoted comma inside the
        # diagnosis shifts the trailing doctor/remarks cells.  A clinician cue
        # is a semantic anchor, so the diagnosis fragments can be joined back
        # without relying on any particular hospital's values.
        doctor_columns = [
            idx for idx, header in enumerate(headers)
            if re.search(r"(?i)\b(?:doctor|physician|clinician|consultant)\b", header)
        ]
        if len(row) > len(headers) and doctor_columns:
            expected_doctor = doctor_columns[0]
            actual_doctor = next(
                (idx for idx in range(max(0, expected_doctor - 1), len(row))
                 if re.match(r"(?i)^\s*(?:dr\.?|doctor\b)", row[idx])),
                None,
            )
            if actual_doctor is not None and actual_doctor > expected_doctor:
                diagnosis_start = max(0, expected_doctor - 1)
                row = (
                    row[:diagnosis_start]
                    + [delimiter.join(row[diagnosis_start:actual_doctor])]
                    + row[actual_doctor:]
                )
        record_ref = next_record_ref()
        is_shifted = original_column_count != len(headers)

        fields: list[FieldNode] = []
        for col_idx, cell_value in enumerate(row):
            if col_idx < len(headers):
                header_name = headers[col_idx]
                field_path = f"col:{col_idx}:{header_name}"
            else:
                header_name = f"__overflow_{col_idx}"
                field_path = f"col:{col_idx}:{header_name}"

            fields.append(
                FieldNode(
                    field_path=field_path,
                    raw_value=cell_value,
                    header_key=header_name,
                    is_structured_key=True,
                    value_type="str",
                )
            )

        first_nonempty = next((cell.strip() for cell in row if cell.strip()), "")
        is_empty_row = not first_nonempty
        is_footer_row = bool(re.match(r"(?i)^(?:total\b|printed\s+by|exported\s+by)", first_nonempty))
        records.append(
            PatientRecord(
                record_ref=record_ref,
                source_ref=source_ref,
                loc=f"row:{row_idx}",
                original_structure={
                    "delimiter": delimiter,
                    "headers": list(headers),
                    "cells": list(row),
                },
                fields=fields,
                field_metadata={
                    "headers": list(headers),
                    "delimiter": delimiter,
                    "expected_columns": len(headers),
                    "actual_columns": original_column_count,
                    "is_shifted_row": is_shifted,
                    "duplicate_headers": duplicate_headers,
                    "has_blank_headers": has_blank_headers,
                    "is_empty_row": is_empty_row,
                    "is_footer_row": is_footer_row,
                },
            )
        )

    return records
