# Purpose: Parses FHIR R4 Bundles/resources (`loc="doc"`), indexes internal references, and decodes text/JSON/XML attachments.
"""FHIR R4 JSON parser supporting Bundles, references, narratives, and attachments."""

from __future__ import annotations

import base64
import binascii
from typing import Any, Callable

from src.contracts import FieldNode, PatientRecord

from ..errors import IngestionQuarantineError
from .json_parser import _escape_pointer_token, _flatten_json_fields


def _index_bundle_references(bundle: dict[str, Any]) -> dict[str, int]:
    """Build safe intra-bundle reference index (fullUrl and ResourceType/id -> entry index)."""
    entries = bundle.get("entry")
    if entries is None:
        return {}
    if not isinstance(entries, list):
        raise IngestionQuarantineError("malformed fhir bundle")

    ref_index: dict[str, int] = {}
    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise IngestionQuarantineError("malformed fhir bundle entry")
        full_url = entry.get("fullUrl")
        if isinstance(full_url, str) and full_url:
            ref_index[full_url] = idx
        resource = entry.get("resource")
        if resource is not None and not isinstance(resource, dict):
            raise IngestionQuarantineError("malformed fhir resource")
        if isinstance(resource, dict):
            rtype = resource.get("resourceType")
            rid = resource.get("id")
            if isinstance(rtype, str) and isinstance(rid, str) and rtype and rid:
                ref_index[f"{rtype}/{rid}"] = idx
    return ref_index


def _extract_attachment_text_nodes(payload: Any) -> list[FieldNode]:
    """Decode base64 UTF-8 text attachments inside FHIR resources so hidden PII is scanned."""
    nodes: list[FieldNode] = []
    stack: list[tuple[Any, str]] = [(payload, "")]

    while stack:
        current, pointer = stack.pop()
        if isinstance(current, dict):
            content_type = current.get("contentType")
            data_b64 = current.get("data")
            if (
                isinstance(data_b64, str)
                and data_b64
                and (
                    not isinstance(content_type, str)
                    or content_type.lower().startswith("text/")
                    or "json" in content_type.lower()
                    or "xml" in content_type.lower()
                )
            ):
                try:
                    decoded_bytes = base64.b64decode(data_b64, validate=True)
                    decoded_text = decoded_bytes.decode("utf-8", errors="strict")
                    nodes.append(
                        FieldNode(
                            field_path=f"{pointer}/data@decoded_attachment",
                            raw_value=decoded_text,
                            header_key="attachment_data",
                            is_structured_key=False,
                            value_type="narrative",
                        )
                    )
                except (binascii.Error, UnicodeDecodeError):
                    pass

            for k, v in reversed(list(current.items())):
                if isinstance(v, (dict, list)):
                    stack.append((v, f"{pointer}/{_escape_pointer_token(str(k))}"))
        elif isinstance(current, list):
            for idx in range(len(current) - 1, -1, -1):
                if isinstance(current[idx], (dict, list)):
                    stack.append((current[idx], f"{pointer}/{idx}"))
    return nodes


def parse_fhir_document(
    parsed_payload: Any,
    source_ref: str,
    next_record_ref: Callable[[], str],
) -> list[PatientRecord]:
    """Parse a FHIR R4 Bundle or standalone Resource into a single `loc='doc'` PatientRecord."""
    if not isinstance(parsed_payload, dict):
        raise IngestionQuarantineError("malformed fhir document")

    resource_type = parsed_payload.get("resourceType")
    if not isinstance(resource_type, str) or not resource_type.strip():
        raise IngestionQuarantineError("missing fhir resourceType")

    bundle_refs: dict[str, int] = {}
    resource_types: list[str] = [resource_type]

    if resource_type == "Bundle":
        bundle_refs = _index_bundle_references(parsed_payload)
        for entry in parsed_payload.get("entry") or []:
            res = entry.get("resource") if isinstance(entry, dict) else None
            if isinstance(res, dict) and isinstance(res.get("resourceType"), str):
                resource_types.append(res["resourceType"])

    fields = _flatten_json_fields(parsed_payload, base_pointer="")
    attachment_nodes = _extract_attachment_text_nodes(parsed_payload)
    fields.extend(attachment_nodes)

    record_ref = next_record_ref()
    return [
        PatientRecord(
            record_ref=record_ref,
            source_ref=source_ref,
            loc="doc",
            original_structure=parsed_payload,
            fields=fields,
            field_metadata={
                "resource_type": resource_type,
                "contained_resource_types": sorted(set(resource_types)),
                "bundle_references": bundle_refs,
                "decoded_attachment_count": len(attachment_nodes),
            },
        )
    ]
