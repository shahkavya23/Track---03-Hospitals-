# Purpose: Iteratively flattens nested/multi-record JSON into FieldNodes with RFC 6901 JSON Pointer `loc`s.
"""Nested and multi-record JSON parser emitting RFC 6901 JSON Pointer locs."""

from __future__ import annotations

from typing import Any, Callable
import copy

from src.contracts import FieldNode, PatientRecord

from ..errors import IngestionQuarantineError


def _escape_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _flatten_json_fields(obj: Any, base_pointer: str = "") -> list[FieldNode]:
    """Iteratively flatten arbitrarily nested JSON into addressable FieldNodes."""
    nodes: list[FieldNode] = []
    stack: list[tuple[Any, str, str]] = [(obj, base_pointer, "root")]

    while stack:
        current, pointer, key_name = stack.pop()
        if isinstance(current, dict):
            # Push in reverse so popped order is deterministic.
            for k, v in reversed(list(current.items())):
                escaped = _escape_pointer_token(str(k))
                child_ptr = f"{pointer}/{escaped}"
                stack.append((v, child_ptr, str(k)))
        elif isinstance(current, list):
            for idx in range(len(current) - 1, -1, -1):
                child_ptr = f"{pointer}/{idx}"
                stack.append((current[idx], child_ptr, key_name))
        else:
            raw_str = "" if current is None else str(current)
            val_type = "null" if current is None else type(current).__name__
            nodes.append(
                FieldNode(
                    field_path=pointer or "/",
                    raw_value=raw_str,
                    header_key=key_name,
                    is_structured_key=True,
                    value_type=val_type,
                )
            )
    return nodes


def _extract_record_entries(payload: Any) -> list[tuple[str, Any, dict[str, Any]]]:
    """Identify logical PatientRecords inside a JSON payload with RFC 6901 locs."""
    if isinstance(payload, list):
        return [(f"/{idx}", item, {"container_type": "root_list"}) for idx, item in enumerate(payload)]

    if isinstance(payload, dict):
        # Look for top-level list-of-dict record containers (e.g. {"visits": [...]})
        array_keys = [
            key
            for key, value in payload.items()
            if isinstance(value, list) and any(isinstance(item, dict) for item in value)
        ]
        if array_keys:
            root_context = {
                key: value
                for key, value in payload.items()
                if key not in array_keys
            }
            entries: list[tuple[str, Any, dict[str, Any]]] = []
            for array_key in array_keys:
                escaped_key = _escape_pointer_token(array_key)
                for idx, item in enumerate(payload[array_key]):
                    entries.append(
                        (
                            f"/{escaped_key}/{idx}",
                            item,
                            {
                                "container_type": "named_array",
                                "array_key": array_key,
                                "root_context": root_context,
                            },
                        )
                    )
            return entries

        return [("/", payload, {"container_type": "single_object"})]

    raise IngestionQuarantineError("unsupported json root type")


def parse_json_document(
    parsed_payload: Any,
    source_ref: str,
    next_record_ref: Callable[[], str],
) -> list[PatientRecord]:
    """Convert pre-validated JSON payload into normalized PatientRecords."""
    # Discover person scopes before flattening. Clinical descendants belong to
    # their closest person; family heads without encounters remain metadata.
    scopes = []
    def discover(obj, pointer=''):
        if isinstance(obj, dict):
            clinical = any(k.casefold() in {'visits', 'encounters', 'diagnosis', 'dx', 'rx', 'vitals', 'labs'} for k in obj)
            person = any(k.casefold() in {'name', 'patient_name', 'patient'} for k in obj)
            if clinical and (person or ('visits' in obj and pointer.count('/') >= 2)):
                scopes.append((pointer, obj))
                return
            for key, value in obj.items():
                discover(value, pointer + '/' + _escape_pointer_token(str(key)))
        elif isinstance(obj, list):
            for idx, value in enumerate(obj):
                discover(value, pointer + '/' + str(idx))
    discover(parsed_payload)
    if scopes and any(pointer.count('/') > 2 for pointer, _ in scopes):
        records = []
        owned_paths = [pointer for pointer, _ in scopes]
        for pointer, obj in scopes:
            records.append(PatientRecord(
                record_ref=next_record_ref(), source_ref=source_ref, loc=pointer,
                original_structure=obj, fields=_flatten_json_fields(obj, pointer),
                field_metadata={'container_type': 'scoped_tree', 'document': parsed_payload},
            ))
        context = [node for node in _flatten_json_fields(parsed_payload)
                   if not any(node.field_path.startswith(p + '/') for p in owned_paths)]
        records.append(PatientRecord(
            record_ref=next_record_ref(), source_ref=source_ref, loc='/',
            original_structure=parsed_payload, fields=context,
            field_metadata={'container_type': 'scoped_tree', 'document': parsed_payload,
                            'is_footer_row': True, 'metadata_only': True},
        ))
        return records
    entries = _extract_record_entries(parsed_payload)
    records: list[PatientRecord] = []

    for loc, structure, metadata in entries:
        record_ref = next_record_ref()
        fields = _flatten_json_fields(structure, base_pointer="" if loc == "/" else loc)

        # Expose root scalar context keys (e.g., top-level hospital/patient metadata)
        # so PII hiding outside the array is still scanned.
        root_context = metadata.get("root_context")
        if isinstance(root_context, dict) and root_context:
            context_fields = _flatten_json_fields(root_context, base_pointer="")
            fields.extend(context_fields)

        records.append(
            PatientRecord(
                record_ref=record_ref,
                source_ref=source_ref,
                loc=loc,
                original_structure=structure,
                fields=fields,
                field_metadata=metadata,
            )
        )

    return records
