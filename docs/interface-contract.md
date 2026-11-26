# RAKSHA Shared Interface Contract (`v0.1.0`)

This document defines the boundary between **Member 1 (Ingestion/Serialization)**, **Member 2 (Detection/Clinical)**, and **Member 3 (Linkage/Privacy)**.

## 1. Official Output Invariants

1. **`records.jsonl` `loc` format:**
   - CSV / TSV: `"row:N"` where `N` is **0-indexed** (`row:0` is the first data row after the header).
   - JSON: RFC 6901 JSON Pointer (e.g., `"/visits/3"` for record arrays, `"/"` for single-object JSON).
   - Text / FHIR R4: `"doc"`.
2. **`records.jsonl` `patient`:**
   - `"PSN-..."` when `ResolutionStatus.RESOLVED`.
   - `null` (`None` in Python) when `UNRESOLVED` or `CONFLICT`. Never fabricate a pseudonym.
   - Resolved `PSN-...` must also be embedded inside the corresponding sanitized record.
3. **`report.json`:**
   - Never contains raw input filenames; uses `input_sha256`.
   - Contains exact `counts`, `timing.seconds`, and `resources.peak_rss_mb`.

## 2. Stage Contracts

### M1 Output -> M2 Input (`SourceFile` & `PatientRecord`)
- M1 delivers `list[SourceFile]`. Quarantined files have `parse_status == ParseStatus.QUARANTINED` and `records == []`.
- Every `PatientRecord` contains:
  - `record_ref`: opaque deterministic ID (`"rec_00000001"`).
  - `loc`: official location string (`"row:0"`, `"/visits/3"`, `"doc"`).
  - `fields`: `list[FieldNode]`, each with UTF-8 `raw_value`, `field_path`, `header_key`, `is_structured_key`, `value_type`.
  - `field_metadata`: safe structural metadata (e.g., `is_shifted_row`, `bundle_references`, `attachment_present`).

### M2 Output -> M3 Input
- M2 populates on each `PatientRecord`:
  - `detections`: `list[DetectionSpan]` with exact character offsets `(start, end)` in `FieldNode.raw_value` (use `start=0, end=len(header_key)` with `is_header_detection=True` or `field_path=f"@key:{path}"` when PII is inside a key/column header).
  - `extracted_patient_attributes`: in-memory normalized signals (e.g. `{"names": [...], "phones": [...], "dobs": [...], "ids": [...]}`). **Never exported.**
  - `clinical_attributes`: protected clinical values that must survive byte-for-byte.
- **Clinical Precedence:** `SpanRole.CLINICAL_PROTECTED` overrides conflicting PII guesses on medications, dosages (`1-0-1`, `Dolo 650 BD x 5 days`), vitals (`BP 150/90`), labs (`HbA1c 7.4%`), and diseases (`Parkinson's disease`).

### M3 Output -> M1 Serialization Input
- M3 receives `Sequence[PatientRecord]` and `hmac_key: bytes` (derived from `RAKSHA_SECRET`).
- M3 produces:
  - `LinkageDecision[]` (using `evidence_categories` codes only, never raw PII)
  - `PatientCluster[]`
  - Sets `record.cluster_ref` and `record.pseudonym_id` (`"PSN-..."` or `None`)
  - Appends `PrivacyDecision[]` to `record.privacy_decisions`, respecting `CLINICAL_PROTECTED` spans and preserving stay duration (`discharge - admission`) under per-patient date shifts.
