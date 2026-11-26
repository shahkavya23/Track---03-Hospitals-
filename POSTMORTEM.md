# CSV-in-text UI incident

## Timeline

1. The user uploaded CSV content as f1.txt through the local web UI.
2. The UI displayed de-identification and a clean badge despite visible patient PII and altered doctors.
3. Inspection confirmed extension-selected parsing, UI-only Python detector/guard/privacy classes, and an unconditional non-quarantine success badge.
4. UI-specific classes were removed; the API now constructs the same default pipeline and policy as main.py.
5. Parser selection now examines decoded content; an independent residual check and conservative UI verification state were added.

## Causes and missing coverage

The API overrode tested pipeline components. Tests exercised the CLI rather than
the API upload route. Extension gates excluded content sniffing. A registry-based
gate could only detect values its weak upstream detector found. UI labels
conflated successful execution with complete independent verification. Rendered
token counts and detected spans were not applied-edit counts.

## Changes and limits

Content-based JSON/FHIR/table/text selection preserves the uploaded filename.
API/CLI parity and independent phone tests each have 50 variants. The API blocks
ZIP export until complete invariant verification exists; the UI reports incomplete
verification rather than promising clean data. Applied field edits are counted
separately from detections. The independent scanner is intentionally limited and
does not certify all person-name, occupation, address or clinical invariants.

XML is identified but quarantined without a supported schema; JSONL is detected
and serialized as one JSON object per line. The forced-free-text 95% name recall target and full 13-file oracle
suite are not certified. Missing oracle files cause the strict CI gate to fail.
The post-change fixture table is generated in INCIDENT_RESULTS.md, including
withheld output and missing files instead of marking them as successful.

## Found independently

- Record namespace based on upload filename caused different REC tokens for identical content under renamed extensions; it now uses the source content hash.
- UI clinical panel claimed 100% preservation without a measured result; the assertion was removed.
- Export was possible whenever a report existed; it now checks server-side verification.
- New normalization can create false positives; independent scans must remain a gate, not a claim of completeness.
- The personal family fixture had been replaced by a FHIR Bundle; immutable versioned regression data prevents accidentally testing a different bug class.
- The clinical validator still used the obsolete loose case-number grammar and falsely quarantined correctly removed uniqueness hints; its grammar now requires numeric identifiers too.
- Repeated CSV headers were counted as patient records; they now remain metadata and are preserved without records.jsonl entries.

No claim is made that the partial measurement harness certifies the six competition
categories or that unresolved regressions are fixed. Re-run and inspect the full
test report before merging.

# Mixed discharge document quarantine incident

## Diagnosis before repair

Content sniffing selected `TEXT`. Ingestion, detection/clinical protection,
linkage, privacy transformation and in-memory rendering all completed without an
exception. Pass 1 found 25 mentions, pass 3 created 29 decisions and the writer
applied 24 edits. The independent gate then found one Aadhaar-shaped value and
one relative-name phrase; the registry found two residual values. The serializer
had no late-redaction transition: its first gate exception went directly to the
quarantine branch. Because published-file metrics excluded quarantined candidates,
the UI incorrectly summarized those 24 in-memory edits as zero.

## Root causes and correction

The bug class was processable mixed content being treated as an indivisible
document. Whole-file JSON/table selection now requires consistent whole-content
evidence; prose containing embedded tables, JSON lines or chat remains text.
Standalone JSON lines are sanitized as structures and written back on one line.
Textual base64 is decoded, independently scanned, sanitized and re-encoded;
binary base64 is replaced. Table and line breaks remain in place.

The publication gate now performs at most three independent, addressable
late-redaction passes, followed by an exact-value residual sweep that excludes
doctor and protected clinical contexts. Only a still-dirty candidate is
quarantined, with a fixed reason code. Reports expose late catches and iteration
counts. The incident input now publishes with zero independent findings, all
doctor mentions retained, its pipe-table shape and JSON-line validity intact,
exact length of stay, and the POD-7 statement preserved.

## Found independently

- A permissive coordinate rule classified ordinary dates and clinical ratios as
  GPS; coordinates now require decimal precision.
- A generic phone rule classified shifted dates as phones and could consume a CSV
  row boundary; generic phone matching is line-bounded, while split-line phones
  require phone-label grammar.
- A late relative sweep erased a bare kinship word; generic kinship terms are now
  disambiguated from names.
- The original fixture inventory contains only 12 names, so the previously
  requested fixture #13 is still explicitly missing rather than invented.

Quarantine remains mandatory for undecodable, binary/unsupported, malformed
whole-document input and any candidate that is still dirty after bounded repair.
It is not used as a substitute for sanitizing processable text.
