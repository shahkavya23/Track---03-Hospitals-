# Secret Wards: architecture audit

Status: migration required. Passing example tests does not establish the invariants below.

## Additional coverage requested after approval

| Area | Status and evidence |
|---|---|
| BOM-less UTF-16 LE/BE | Accidental: encoding:decode_bytes_to_utf8 delegates NUL-containing input to statistical inference. |
| cp1252 | Guaranteed decoding path: encoding:decode_bytes_to_utf8 fallback; semantic correctness still needs fixtures. |
| Mojibake / Kruti Dev | Violated: encoding:decode_bytes_to_utf8 has no explicit repair/transliteration stage. |
| NBSP / zero-width / homoglyphs / multilingual digits | Partial/accidental: normalization/unicode_map; coverage must be tested per script before claiming a guarantee. |
| Encrypted raw temp spill | Violated for any future spill; no encryption helper exists. Publish gate renders unverified output in memory. |
| Cleanup on serialization failure | Guaranteed for gate staging: serializer:serialize_all finally removes verified staging files. Earlier stages still require audit. |
| Fixed-vocabulary log helper | Violated: no shared helper exists. |
| Content-free CLI errors | Guaranteed at CLI boundary: main:main prints exception class only. |
| Read-only inputs | Accidental: ingestion reads inputs; no mounted-read-only regression test yet. |
| 5x runtime/RSS | Unmeasured; unavailable full practice corpus prevents the requested benchmark. |

Available oracle content: tests/My personal testing/t1 (YMC register content),
tests/My personal testing/family_export.json (user-pasted family JSON content).
The ten named first-set oracle files are absent from this repository inventory.
The exact filenames ymc_ipd_register_2024.csv and city_clinic_family_visits.json
are not supplied as source fixtures; the two available files above contain their
user-provided equivalents. No missing oracle replacements were invented.

safe-1 work: in-memory per-file rendering, detected-PII residual gate, clinical
validation, atomic sanitized-byte publication and quarantine on gate failure.
Residual registry currently covers detected direct identifiers only; container-key,
cross-script and global mention coverage remains for later migration steps.

```text
UniversalIngestor -> format parsers -> PatientRecord / FieldNode
 -> MultilingualPIIDetector + ClinicalIntegrityGuard
 -> ConservativeLinkageEngine (blocking -> matcher -> complete-link clustering)
 -> AdaptivePrivacyEngine (PSN -> structured transforms -> QI generalizer)
 -> SafeOutputSerializer -> writers -> post-write validator
```

## Invariant assessment

| Invariant | Current status and evidence |
|---|---|
| I1 Person-scoped PSNs | Violated: json_parser:_extract_record_entries treats a nested document without top-level arrays as one patient. |
| I2 All node kinds scanned | Violated: json_parser:_flatten_json_fields exposes scalar leaves, not container keys; writers handle filenames and headers separately. |
| I3 Zero residual leaks | Not guaranteed: serializer:serialize_all has no global in-memory PII registry or residual repair loop. |
| I4 Protected content unchanged | Partial: span_applier:apply_decisions_to_field permits broad token overrides; validator checks selected extracted strings rather than all protected spans. |
| I5 All date intervals preserved | Partial: structured:_safe_date_offsets covers selected fields; unsupported narrative dates become tokens and unrecognised dates may survive. |
| I6 Truthful ages / DOB dates | Violated: structured:classify_field maps DOB to AGE_DOB; generalize_age reads the first number of ranges. |
| I7 Structural validity | Partial: tabular parser repairs known shifted rows; JSON reconstruction relies on three container shapes; FHIR validator checks resourceType only. |
| I8 Global consistency | Partial: structured:structure_aware_decisions sweeps locality aliases; singleton anchors depend on record refs and REC tokens use numeric tails without namespace. |
| I9 Determinism | Violated globally: pipeline timing/RSS vary; age and date bounds use wall clock; record refs depend on input ordering. |
| I10 Honest counts | Partial: serializer counts rendered tokens, including potential pre-existing tokens; no applied-event ledger exists. |
| I11 Crash safety | Violated: serializer writes final files before validator runs; main catches only at whole-run level. |

## Missing guarantees behind known failures

- Destroyed headers, leaked container keys and attachment names: I2; schema elements are not first-class nodes.
- Partial names, aliases and cross-column locations: I3/I8; local detection lacks a complete global mention registry.
- One PSN for a family and operator: I1; flattening happens before person segmentation and role assignment.
- Shared phones, newborns and twins: I1; household attributes and person evidence need explicit ownership.
- DOB bands and truncated age ranges: I6; overloaded role inference and first-number parsing.
- Incomplete date formats, future boundaries and household incoherence: I5/I9; multiple transform paths and wall-clock dependencies.
- Binary attachments copied, unsafe errors and half-written outputs: I2/I11; no atomic per-file publish gate.
- Report overclaims: I10; decisions and actual applied edits are not one event stream.

## Migration sequence

1. Add invariant tests for person segmentation, metadata ownership, full DOB and age ranges before implementation.
2. Introduce UDM nodes and explicit record scopes; adapt existing readers without replacing working CSV parsing.
3. Segment nested person objects with clinical descendants; metadata/relatives get no patient ownership. Reconstruct from the original tree with pointer edits.
4. Extract mentions and protected spans globally; resolve persons and households separately; use stable content fingerprints and namespaced IDs.
5. Route every rewrite through one overlap resolver and applied-event ledger; unify date and geography policies.
6. Stage sanitized files privately; residual-scan all surfaces; atomically publish or quarantine each file.
7. Add seeded adversarial generation, metamorphic tests, scorer and self-attack; run three seeds and available hand-built inputs.
8. Record measured results and remaining limits. Do not claim unseen oracle files were tested.

## Immediate safety finding

The generated `output-family` artifact is diagnostic and unsafe for release. Its successful CLI exit is not evidence of privacy correctness. Existing CSV outputs do not validate the nested JSON path.
