# Incident change summary and acceptance status

| Files | Change |
|---|---|
| backend_server.py | Removed UI-only detection/guard/privacy implementation; shared pipeline/policy; verification payload; server-side export denial; content-free request logging; upload containment check; secret value no longer exposed in status. |
| ingestion/format_detect.py, ingestor.py | Decode before parser choice; recognize JSON, JSONL, FHIR and consistent delimited content regardless of extension; identify/quarantine unsupported XML. |
| ingestion/parsers/tabular.py | Sniff delimiters; annotate repeated headers. |
| contracts/enums.py | Represent JSONL explicitly. |
| detection/detector.py, regex_rules.py | Avoid interpreting repeated headers as people; recognize masked Aadhaar shapes. |
| privacy/structured.py, pipeline.py | Numeric case-marker grammar; clinician-field preservation; extension-independent content namespace. |
| security/independent_scan.py | Independent count-only phone/ID/email/PIN/relation/token checks with script-digit and zero-width normalization. |
| serialization/publish_gate.py, serializer.py, validator.py, writers.py | Gate independent findings; safe diagnostic reason vocabulary; JSONL output/validation; preserve repeated headers; documented text PSN prefix. |
| serialization/span_applier.py, contracts/models.py | Record actually applied value edits and export aggregate applied_replacements. Header/key/file rename accounting is not yet complete. |
| frontend/src/App.jsx, Header.jsx, tabs/IngestTab.jsx, DiffTab.jsx, ClinicalTab.jsx | Remove assumed clean/preservation badges; count applied edits; block export while verification is incomplete. |
| tests/test_incident_api.py, test_ingestion/test_content_sniffing.py | 50 API/CLI upload variants; 50 independent-script phone variants; 50 case-marker/masked-ID variants; 110 content-sniff cases. |
| tests/incident_report.py, fixtures/incident_registration.csv | Run available real fixture content through original-extension/text/paste variants and report withholding/missing files explicitly. |
| .github/workflows/incident-regression.yml | API/CLI regression job and strict missing-oracle gate. |

## Not accepted for merge

The partial benchmark's validity category fell from 100 to 89.552 because the
stronger gate withholds unsafe/unverified probe outputs. Under the requested
one-point rule this change is not accepted for merge. Safety containment is not a
substitute for restoring useful, correct output. The original family regression
now uses a versioned fixture recovered from commit 8111469; the user's personal
file had been replaced with a different FHIR Bundle and was left unchanged.
The Sonpur clinical gate mismatch was traced to the validator's obsolete loose
case-number expression and corrected. Sonpur, YMC and the recovered family
fixture now publish with API/CLI parity under all three filename/paste variants.

Forced-free-text name recall >=95%, full independent person/address gazetteer
coverage, all-invariant certification, complete applied-event accounting and
unsupported XML schema processing remain unfinished. No green badge or ZIP
export is permitted on the basis of the partial scanner.

The available fixture table is INCIDENT_RESULTS.md. Only 12 oracle names were
specified in the incident's referenced corpus; three have supplied content,
nine are missing, and the requested thirteenth is unspecified. No replacements
were invented. The six-category harness itself remains provisional as described
in tests/MEASUREMENT.md. Holdout outputs were not inspected for examples.

## Mixed-document follow-up

| Files | Change |
|---|---|
| `src/ingestion/format_detect.py` | Require whole-content consistency; fall back from embedded JSON/table fragments to processable text. |
| `src/security/independent_scan.py` | Addressable late findings for phones, word/split phones, UPI, voter/bank/PMJAY/donor IDs, coordinates, vehicles, landmarks, handles, chat speakers and nicknames; lot/date disambiguation. |
| `src/serialization/publish_gate.py` | Three-pass re-redaction, JSON-line and base64 sub-handlers, clinician/clinical/kinship protection, exact residual sweep. |
| `src/serialization/serializer.py`, `src/contracts/models.py` | Run repair before quarantine; fixed reason codes; report late catches and iterations. |
| `src/serialization/writers.py` | Preserve the original text layout without injecting an extra patient line. |
| `src/privacy/structured.py` | General staff/other-person role grammar and quasi-identifier classes. |
| `tests/test_mixed_document_incident.py` | 300 generated variants plus an end-to-end mixed-document regression. |
| `tests/gen/*`, `tests/score.py` | Disjoint mixed templates and separate processable/unprocessable quarantine rates. |
| `tests/incident_report.py` | Fourteen-slot table, with missing oracle #13 explicit and structure/POD checks for the new incident. |

## Verification and regression decision

The full local suite passes: **872 passed**. The incident file publishes through
the live API as one sanitized file with 43 applied replacements, 11 independent
late catches, one late-redaction iteration and zero final residual findings.
All five doctor mentions remain, the pipe layout matches, the embedded JSON line
parses, LOS is exact and POD-7 remains exact. API and CLI artifacts match.

| Seed | Profile | Privacy | PII | Medical | Identity | Validity | Reliability | Total |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | tune | 100.000 | 98.863 | 100.000 | 100.000 | 100.000 | 100.000 | 99.811 |
| 2 | tune | 99.667 | 98.875 | 100.000 | 100.000 | 100.000 | 100.000 | 99.757 |
| 3 | tune | 100.000 | 98.852 | 100.000 | 100.000 | 100.000 | 100.000 | 99.809 |
| 4 | holdout | 81.667 | 98.717 | 66.667 | 100.000 | 100.000 | 100.000 | 71.175 |
| 5 | holdout | 79.000 | 98.681 | 66.667 | 100.000 | 100.000 | 100.000 | 70.725 |
| 6 | holdout | 80.667 | 98.686 | 66.667 | 100.000 | 100.000 | 100.000 | 71.003 |

No measured category decreased from `measurement-incident-final`; therefore the
one-point rejection rule did not fire. Every seed reports a 0% quarantine rate
for processable inputs and 100% for unprocessable bait. The benchmark now also
contains one mixed-document file, so this is a versioned expanded matrix rather
than a perfectly identical corpus comparison. Holdout examples were not opened;
only aggregate numbers and quarantine rates were read.

The missing oracle fixtures still prevent full-corpus certification. The UI
therefore continues to show verification as incomplete and keeps ZIP export
blocked, even though this incident file is sanitized rather than quarantined.
