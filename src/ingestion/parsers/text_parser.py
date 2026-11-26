"""Unstructured multilingual clinical text (.txt) parser."""

from __future__ import annotations

from typing import Callable

from src.contracts import FieldNode, PatientRecord

from ..errors import IngestionQuarantineError


def parse_text_document(
    text: str,
    source_ref: str,
    next_record_ref: Callable[[], str],
) -> list[PatientRecord]:
    """Wrap UTF-8 clinical text as a single `loc='doc'` PatientRecord."""
    if not text.strip():
        raise IngestionQuarantineError("empty file")

    record_ref = next_record_ref()
    return [
        PatientRecord(
            record_ref=record_ref,
            source_ref=source_ref,
            loc="doc",
            original_structure=text,
            fields=[
                FieldNode(
                    field_path="doc",
                    raw_value=text,
                    header_key="doc",
                    is_structured_key=False,
                    value_type="narrative",
                )
            ],
            field_metadata={
                "line_count": len(text.splitlines()),
                "char_count": len(text),
            },
        )
    ]
