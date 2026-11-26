# RAKSHA Architecture

## 1. Design Principles

1. **Zero Leakage by Construction:** Raw filenames (`SourceFile.relative_path`), raw patient attributes (`extracted_patient_attributes`), and `RAKSHA_SECRET` are strictly internal. Logs, exceptions, `report.json`, and `records.jsonl` never emit them.
2. **In-Memory Processing (No Plaintext Temp Files):** Records are normalized into `dataclasses(slots=True)` in memory, processed across M1 -> M2 -> M3 -> M1, and serialized directly to `output/`.
3. **Fail-Safe Quarantine:** Unsupported, symlinked, path-escaping, empty, oversized, undecodable, or malformed files are never copied half-cleaned into `sanitized/`; they are recorded as `quarantined` with a safe reason code in `report.json`.
4. **Deterministic Execution:** Directory traversal, record ID assignment, linkage clustering, HMAC pseudonym generation, and date shifting are 100% deterministic for a given `(input, RAKSHA_SECRET)`.
5. **Resource Budget:** Pure CPU, offline execution under 2 vCPUs, 4 GB RAM, and 15 minutes per run.

## 2. Pipeline Stages

```text
[1] Ingestion (Member 1 — src/ingestion/)
    Input Directory -> Safe Traversal -> Streaming SHA-256 -> Encoding Normalization
    -> Format Detection (CSV/TSV/JSON/FHIR R4/TXT) -> SourceFile + PatientRecord[]
        │
        ▼
[2] Multilingual Detection & Clinical Integrity (Member 2 — src/detection/, src/clinical/)
    PatientRecord.fields -> DetectionSpan[] (DIRECT_PII, QUASI_IDENTIFIER, CLINICAL_PROTECTED)
    + extracted_patient_attributes (in-memory only) + clinical_attributes
        │
        ▼
[3] Linkage, Pseudonymization & QI Privacy (Member 3 — src/linkage/, src/privacy/)
    PatientRecord[] + RAKSHA_SECRET -> LinkageDecision[] + PatientCluster[]
    -> pseudonym_id ("PSN-..." or None) + PrivacyDecision[]
        │
        ▼
[4] Safe Serialization & Reporting (Member 1 — src/serialization/, src/reporting/)
    -> output/sanitized/... (format-preserved UTF-8, safe filenames/headers, embedded PSN-...)
    -> output/records.jsonl (file, loc, patient)
    -> output/report.json   (input_sha256, output, status, counts, timing, peak_rss_mb)
```

## 3. Logical In-Memory Data Model

| Collection | Key | Notes |
| :--- | :--- | :--- |
| `SOURCE_FILES` | `source_ref` | Holds `source_sha256`, `format`, `encoding`, `parse_status`, `quarantine_reason`. |
| `PATIENT_RECORDS` | `record_ref` | Holds `source_ref`, official `loc`, `original_structure`, `fields`, `field_metadata`. |
| `DETECTIONS` | `(record_ref, field_path)` | `DetectionSpan` list with offsets, `category`, `role`, `confidence`. |
| `LINKAGE_DECISIONS` | `(record_ref_a, record_ref_b)` | `MATCH` / `NON_MATCH` / `ABSTAIN`, `score`, `evidence_categories` (no raw PII). |
| `PATIENT_CLUSTERS` | `cluster_ref` | Internal cluster membership, `resolution_status`, exported `pseudonym_id`. |
| `PRIVACY_DECISIONS` | `(record_ref, field_path)` | Transform type, safe replacement/params, clinical constraints. |
| `AUDIT_METRICS` | singleton | Exact counts matching `report.json` + runtime seconds + peak RSS MB. |
