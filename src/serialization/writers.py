# Purpose: Format-preserving UTF-8 writers for sanitized CSV, TSV, JSON, FHIR R4, and clinical text outputs.
"""Format-preserving safe writers for CSV, TSV, JSON, FHIR R4, and text."""

from __future__ import annotations

import base64
import copy
import csv
import json
from pathlib import Path, PurePosixPath
from typing import Any

from src.contracts import FileFormat, PatientRecord, PrivacyDecision, SourceFile, TransformType

from .span_applier import apply_decisions_to_field


def resolve_safe_output_path(source: SourceFile, output_dir: Path) -> Path:
    """Resolve destination inside output_dir/sanitized/, renaming PII filenames if flagged."""
    if source.sanitized_relative_path is None:
        raise ValueError("Cannot serialize a quarantined source file")

    rel = source.sanitized_relative_path
    has_filename_pii = any(
        bool(rec.field_metadata.get("filename_has_pii")) for rec in source.records
    )
    if has_filename_pii and rel == f"sanitized/{source.relative_path}":
        posix = PurePosixPath(source.relative_path)
        parent = posix.parent.as_posix()
        opaque_name = f"doc_{source.source_sha256[:12]}{posix.suffix.lower()}"
        rel = f"sanitized/{opaque_name}" if parent == "." else f"sanitized/{parent}/{opaque_name}"
        source.sanitized_relative_path = rel

    sanitized_root = (output_dir / "sanitized").resolve()
    sanitized_root.mkdir(parents=True, exist_ok=True)
    target = (output_dir / rel).resolve()
    if not target.is_relative_to(sanitized_root):
        raise ValueError("Sanitized output path escapes sanitized/ root")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _unescape_pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def _split_pointer(pointer: str) -> list[str]:
    stripped = pointer.lstrip("/")
    if not stripped:
        return []
    return [_unescape_pointer_token(part) for part in stripped.split("/")]


def _navigate_parent(root: Any, tokens: list[str]) -> tuple[Any, str | int] | None:
    if not tokens:
        return None
    curr = root
    for tok in tokens[:-1]:
        if isinstance(curr, dict) and tok in curr:
            curr = curr[tok]
        elif isinstance(curr, list) and tok.isdigit() and int(tok) < len(curr):
            curr = curr[int(tok)]
        else:
            return None
    last = tokens[-1]
    if isinstance(curr, dict):
        return curr, last
    if isinstance(curr, list) and last.isdigit() and int(last) < len(curr):
        return curr, int(last)
    return None


def _contains_pseudonym(obj: Any, pseudonym_id: str) -> bool:
    return pseudonym_id in json.dumps(obj, ensure_ascii=False)


def _apply_json_decisions(
    obj: Any,
    record: PatientRecord,
    base_prefix: str = "",
) -> Any:
    """Apply field and key PrivacyDecisions to a JSON object/list copy."""
    cloned = copy.deepcopy(obj)

    # Apply value decisions once per unique field_path.
    field_map = {node.field_path: node for node in record.fields}
    seen_paths: set[str] = set()
    for dec in record.privacy_decisions:
        if (
            dec.field_path.startswith("@key:")
            or dec.field_path.endswith("@decoded_attachment")
            or dec.transform_type == TransformType.PRESERVE_CLINICAL
            or dec.field_path in seen_paths
        ):
            continue
        if dec.field_path not in field_map and not dec.field_path.startswith("/"):
            continue
        seen_paths.add(dec.field_path)
        rel_pointer = dec.field_path
        if base_prefix and rel_pointer.startswith(base_prefix + "/"):
            rel_pointer = rel_pointer[len(base_prefix) :]
        elif base_prefix and rel_pointer == base_prefix:
            rel_pointer = "/"

        tokens = _split_pointer(rel_pointer)
        if not tokens:
            if isinstance(cloned, str):
                cloned, _ = apply_decisions_to_field(cloned, record, dec.field_path)
            continue

        located = _navigate_parent(cloned, tokens)
        if located is None:
            continue
        parent, key_or_idx = located
        if isinstance(parent, dict) and key_or_idx not in parent:
            continue
        current_val = parent[key_or_idx]
        if current_val is None or isinstance(current_val, (str, int, float, bool)):
            raw_str = "" if current_val is None else str(current_val)
            new_str, _ = apply_decisions_to_field(raw_str, record, dec.field_path)
            parent[key_or_idx] = new_str

    # Apply key-PII renames (`@key:/path/to/key`).
    for dec in record.privacy_decisions:
        if not dec.field_path.startswith("@key:") or dec.replacement_value is None:
            continue
        raw_ptr = dec.field_path[len("@key:") :]
        if base_prefix and raw_ptr.startswith(base_prefix + "/"):
            raw_ptr = raw_ptr[len(base_prefix) :]
        tokens = _split_pointer(raw_ptr)
        located = _navigate_parent(cloned, tokens)
        if located is None:
            continue
        parent, old_key = located
        if isinstance(parent, dict) and isinstance(old_key, str) and old_key in parent:
            val = parent.pop(old_key)
            parent[dec.replacement_value] = val

    return cloned


def write_tabular_source(source: SourceFile, target_path: Path) -> None:
    """Write sanitized CSV or TSV preserving structure and clinical values."""
    if not source.records:
        target_path.write_text("", encoding="utf-8")
        return

    first_struct = source.records[0].original_structure
    delimiter = "\t" if source.format == FileFormat.TSV else str(first_struct.get("delimiter", ","))
    orig_headers: list[str] = list(first_struct["headers"])
    out_headers = list(orig_headers)

    # Apply header-level PII renames if present (`@header:<idx>` or `@header:<name>`).
    for rec in source.records:
        for dec in rec.privacy_decisions:
            if not dec.field_path.startswith("@header:") or dec.replacement_value is None:
                continue
            target_tok = dec.field_path[len("@header:") :]
            if target_tok.isdigit() and int(target_tok) < len(out_headers):
                out_headers[int(target_tok)] = dec.replacement_value
            else:
                for idx, hname in enumerate(orig_headers):
                    if hname == target_tok:
                        out_headers[idx] = dec.replacement_value

    sanitized_rows: list[list[str]] = []
    needs_psn_column = False

    for rec in source.records:
        cells = list(rec.original_structure["cells"])
        new_cells: list[str] = []
        for col_idx, cell in enumerate(cells):
            if col_idx < len(orig_headers):
                fpath = f"col:{col_idx}:{orig_headers[col_idx]}"
            else:
                fpath = f"col:{col_idx}:__overflow_{col_idx}"
            updated, _ = apply_decisions_to_field(cell, rec, fpath)
            new_cells.append(updated)

        if rec.pseudonym_id is not None and rec.pseudonym_id not in new_cells:
            needs_psn_column = True
        sanitized_rows.append(new_cells)

    if needs_psn_column:
        out_headers.append("raksha_patient_id")
        for rec, row in zip(source.records, sanitized_rows):
            row.append(rec.pseudonym_id or "")

    with target_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter, lineterminator="\n")
        writer.writerow(out_headers)
        writer.writerows(sanitized_rows)


def write_json_source(source: SourceFile, target_path: Path) -> None:
    """Reconstruct and write sanitized JSON preserving original layout."""
    if not source.records:
        target_path.write_text("{}\n", encoding="utf-8")
        return

    container_type = source.records[0].field_metadata.get("container_type", "single_object")

    if container_type == "single_object":
        rec = source.records[0]
        obj = _apply_json_decisions(rec.original_structure, rec, base_prefix="")
        if (
            rec.pseudonym_id is not None
            and isinstance(obj, dict)
            and not _contains_pseudonym(obj, rec.pseudonym_id)
        ):
            obj["patient_id"] = rec.pseudonym_id
        payload: Any = obj

    elif container_type == "root_list":
        items: list[Any] = []
        for idx, rec in enumerate(source.records):
            item = _apply_json_decisions(rec.original_structure, rec, base_prefix=f"/{idx}")
            if (
                rec.pseudonym_id is not None
                and isinstance(item, dict)
                and not _contains_pseudonym(item, rec.pseudonym_id)
            ):
                item["patient_id"] = rec.pseudonym_id
            items.append(item)
        payload = items

    else:
        # named_array (e.g. {"facility": "...", "visits": [...]})
        root_ctx = copy.deepcopy(source.records[0].field_metadata.get("root_context", {}))
        # Sanitize root_context decisions via the first record's context fields.
        root_ctx = _apply_json_decisions(root_ctx, source.records[0], base_prefix="")
        if not isinstance(root_ctx, dict):
            root_ctx = {}

        arrays: dict[str, list[Any]] = {}
        for rec in source.records:
            arr_key = str(rec.field_metadata.get("array_key", "records"))
            arr_list = arrays.setdefault(arr_key, [])
            item = _apply_json_decisions(
                rec.original_structure,
                rec,
                base_prefix=rec.loc,
            )
            if (
                rec.pseudonym_id is not None
                and isinstance(item, dict)
                and not _contains_pseudonym(item, rec.pseudonym_id)
            ):
                item["patient_id"] = rec.pseudonym_id
            arr_list.append(item)

        root_ctx.update(arrays)
        payload = root_ctx

    target_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_fhir_source(source: SourceFile, target_path: Path) -> None:
    """Write valid sanitized FHIR R4 JSON including re-encoded text attachments."""
    if not source.records:
        raise ValueError("FHIR source must contain a document record")

    rec = source.records[0]
    fhir_obj = _apply_json_decisions(rec.original_structure, rec, base_prefix="")

    # Re-encode any sanitized `@decoded_attachment` fields back into base64 `data`.
    node_map = {n.field_path: n.raw_value for n in rec.fields}
    seen_att_paths: set[str] = set()
    for dec in rec.privacy_decisions:
        if not dec.field_path.endswith("/data@decoded_attachment") or dec.field_path in seen_att_paths:
            continue
        seen_att_paths.add(dec.field_path)
        raw_att = node_map.get(dec.field_path)
        if raw_att is None:
            continue
        sanitized_att, _ = apply_decisions_to_field(raw_att, rec, dec.field_path)
        node_map[dec.field_path] = sanitized_att
        target_ptr = dec.field_path[: -len("@decoded_attachment")]
        located = _navigate_parent(fhir_obj, _split_pointer(target_ptr))
        if located is not None:
            parent, key_or_idx = located
            parent[key_or_idx] = base64.b64encode(sanitized_att.encode("utf-8")).decode("ascii")

    if rec.pseudonym_id is not None and not _contains_pseudonym(fhir_obj, rec.pseudonym_id):
        if isinstance(fhir_obj, dict):
            if fhir_obj.get("resourceType") == "Bundle":
                embedded = False
                for entry in fhir_obj.get("entry") or []:
                    res = entry.get("resource") if isinstance(entry, dict) else None
                    if isinstance(res, dict) and res.get("resourceType") == "Patient":
                        res["id"] = rec.pseudonym_id
                        embedded = True
                        break
                if not embedded:
                    fhir_obj["identifier"] = {
                        "system": "urn:raksha:pseudonym",
                        "value": rec.pseudonym_id,
                    }
            elif fhir_obj.get("resourceType") == "Patient":
                fhir_obj["id"] = rec.pseudonym_id
            else:
                identifiers = fhir_obj.setdefault("identifier", [])
                if isinstance(identifiers, list):
                    identifiers.append(
                        {"system": "urn:raksha:pseudonym", "value": rec.pseudonym_id}
                    )

    if not isinstance(fhir_obj, dict) or not isinstance(fhir_obj.get("resourceType"), str):
        raise ValueError("Serialized FHIR output lost required resourceType")

    target_path.write_text(
        json.dumps(fhir_obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def write_text_source(source: SourceFile, target_path: Path) -> None:
    """Write sanitized UTF-8 clinical text note."""
    if not source.records:
        target_path.write_text("", encoding="utf-8")
        return

    rec = source.records[0]
    raw_text = str(rec.original_structure)
    sanitized_text, _ = apply_decisions_to_field(raw_text, rec, "doc")
    if rec.pseudonym_id is not None and rec.pseudonym_id not in sanitized_text:
        sanitized_text = f"[PATIENT_ID: {rec.pseudonym_id}]\n{sanitized_text}"
    target_path.write_text(sanitized_text, encoding="utf-8")
