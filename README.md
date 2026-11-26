# RAKSHA — Multilingual Healthcare Privacy Firewall

> Yugaantar DevForge — Track 3: **Secret Wards**  
> Offline, CPU-only, LLM-free healthcare de-identification, cross-script patient linkage, and privacy-preserving transformation pipeline.

---

## Architecture Overview

```text
input/ (CSV, TSV, JSON, FHIR R4, TXT)
  │
  ▼
[Member 1] Ingestion Layer (src/ingestion/)
  ├── Path containment, symlink rejection, streaming SHA-256
  ├── BOM & legacy encoding normalization -> strict UTF-8
  ├── Format detection & FHIR R4 / JSON / CSV / TSV / TXT parsing
  └── Quarantine for unsupported, empty, oversized, or corrupted files
  │
  ▼
[Member 2] Multilingual Detection & Clinical Integrity (src/detection/, src/clinical/)
  ├── English, Hindi (Devanagari) & Hinglish PII + Indian IDs
  ├── Hidden PII in CSV headers, JSON keys, filenames & attachments
  └── Clinical span protection (meds, doses, vitals, labs, diagnoses)
  │
  ▼
[Member 3] Patient Linkage & Privacy Layer (src/linkage/, src/privacy/)
  ├── Cross-hospital / cross-script record linkage without false merges
  ├── Keyed-HMAC pseudonyms (PSN-...) driven by RAKSHA_SECRET (null if unresolved)
  └── Quasi-identifier transforms (per-patient date shift, age bands, generalization)
  │
  ▼
[Member 1] Safe Serialization, Reporting & Validation (src/serialization/, src/reporting/)
  ├── output/sanitized/   (format-preserved UTF-8, safe filenames/headers)
  ├── output/report.json  (SHA-256 file inventory, true counts, timing, peak RSS)
  └── output/records.jsonl (file, loc, patient pseudonym or null)
```

---

## Setup & Execution

```bash
pip install -r requirements.txt
```

Set the runtime secret key and run:

```bash
# Linux / macOS
export RAKSHA_SECRET="your-secret-key"
python main.py --input /path/to/input --output /path/to/output

# Windows PowerShell
$env:RAKSHA_SECRET = "your-secret-key"
python main.py --input path\to\input --output path\to\output
```

---

## Running Tests

```bash
# Using pytest (if installed)
pytest

# Or using Python standard library unittest
python -m unittest discover -s tests -p "test_*.py" -v
```

---

## Team Ownership

| Member | Owned Modules |
| :--- | :--- |
| **Member 1** | `src/contracts/`, `src/ingestion/`, `src/serialization/`, `src/reporting/`, `src/pipeline.py`, `main.py`, `raksha.toml`, `docs/` |
| **Member 2** | `src/detection/`, `src/clinical/`, `tests/test_detection/` |
| **Member 3** | `src/linkage/`, `src/privacy/`, `tests/test_privacy_linkage/` |

See [docs/architecture.md](docs/architecture.md) and [docs/interface-contract.md](docs/interface-contract.md) for the exact shared contracts.
