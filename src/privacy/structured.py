"""Structure-aware privacy transforms shared by tabular, JSON and FHIR fields."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import unicodedata
from typing import Iterable, Sequence

from src.contracts import PatientRecord, PrivacyDecision, SpanRole, TransformType
from src.privacy.date_shift import derive_date_offset, shift_date_value
from src.privacy.generalization import age_band
from src.privacy.locations import hierarchy_outputs
from src.detection.normalization.names import normalize_person_name


_KINSHIP_ONLY = frozenset({
    "nani", "nana", "dadi", "dada", "maa", "papa", "bhai", "behen", "beta",
    "beti", "bahu", "chacha", "mama", "bua", "kaka", "didi", "ji", "sahab",
    "self", "unknown",
})


def _tokens(value: str) -> set[str]:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return {p for p in re.split(r"[\W_]+", value.casefold()) if p}


def classify_field(header: str, values: Iterable[str] = ()) -> str:
    """Classify an arbitrary schema label without relying on exact column names."""
    t = _tokens(header)
    if t & {"doctor", "dr", "physician", "clinician", "surgeon", "consultant"}:
        return "DOCTOR"
    if t & {"diagnosis", "dx", "provisional", "condition", "complaint"}:
        return "DIAGNOSIS"
    if t & {"department", "dept", "ward", "speciality", "specialty"}:
        return "DEPT"
    if t & {"sex", "gender"}:
        return "SEX"
    if t & {'dob', 'birth', 'birthdate'}:
        return 'DOB'
    if 'age' in t:
        return 'AGE'
    if t & {"doa", "dod", "date", "admission", "discharge", "datetime", "timestamp"}:
        return "DATETIME" if t & {"datetime", "timestamp"} else "DATE"
    if t & {"address", "addr", "residence", "locality", "village", "town", "city"}:
        return "ADDRESS"
    if t & {"phone", "mobile", "contact", "telephone", "whatsapp", "tel"}:
        return "PHONE"
    # A qualifier such as "name (as per Aadhaar)" is still a name column.
    if (t & {"name", "patient", "pt", "beneficiary", "subject"}) and not t & {"doctor", "guardian"}:
        return "PATIENT_NAME"
    if t & {"aadhaar", "aadhar", "abha", "pan", "proof", "document", "dl", "license", "licence"}:
        return "ID_DOC"
    if t & {"ipd", "opd", "uhid", "mrn", "registration", "regn"} or (
        "record" in t and bool(t & {"id", "no", "number"})
    ):
        return "RECORD_ID"
    if t & {"guardian", "relative", "father", "mother", "spouse", "husband", "wife", "kin"}:
        return "RELATIVE"
    sample = [v.strip() for v in values if v.strip()][:20]
    if sample:
        if sum(bool(re.fullmatch(r"[MFOmfo]", v)) for v in sample) / len(sample) > .8:
            return "SEX"
        if sum(bool(re.fullmatch(r"\+?[\d\s().-]{8,18}", v)) for v in sample) / len(sample) > .8:
            return "PHONE"
    return "FREE_TEXT"


def typed_token(category: str) -> str:
    c = category.upper()
    mapping = {
        "PATIENT_NAME": "[PATIENT]", "PERSON_NAME": "[PATIENT]",
        "RELATIVE_NAME": "[RELATIVE]", "CLINICIAN_NAME": "[STAFF]",
        "STAFF_NAME": "[STAFF]", "STAFF_IDENTIFIER": "[STAFF]", "PHONE": "[PHONE]", "AADHAAR": "[AADHAAR]",
        "PAN": "[PAN]", "ABHA": "[ABHA]", "DL": "[DL]", "EMAIL": "[EMAIL]",
        "IP": "[IP]", "USERNAME": "[USERNAME]", "CASE_NO": "[CASE_NO]",
        "ID_MARK": "[ID_MARK]", "ADDRESS": "[ADDRESS]", "PIN_CODE": "[ADDRESS]",
        "UHID": "[CASE_NO]", "MRN": "[CASE_NO]", "PATIENT_IDENTIFIER": "[CASE_NO]",
        "INSURANCE_ID": "[CASE_NO]", "HEADER_PII": "[REDACTED]", "KEY_PII": "[REDACTED]",
    }
    return mapping.get(c, "[REDACTED]")


def sanitize_schema_label(label: str) -> str:
    """Remove embedded identity values while retaining a key's semantic words."""
    result = re.sub(r"(?<!\d)(?:\+?\d[\d\s().-]{7,}\d)(?!\d)", "[PHONE]", label)
    result = re.sub(
        r"(?i)(verified\s+by|printed\s+by|exported\s+by|typed\s+by)\s+(?:Sr\.?\s*)?[A-Z][\w.-]*(?:\s+[A-Z][\w.-]*){0,2}",
        r"\1 [STAFF]",
        result,
    )
    if _tokens(result) & {"patient", "pt", "relative", "guardian"}:
        parts = re.split(r"([/_-])", result)
        safe = {"patient", "pt", "relative", "guardian", "name", "id", "key", "field", "value"}
        parts = ["[PATIENT]" if p.isalpha() and p.casefold() not in safe else p for p in parts]
        result = "".join(parts)
    return result


def _record_token(secret: bytes, raw: str, namespace: str = '') -> str:
    normalized = unicodedata.normalize("NFKC", raw).upper()
    numeric_parts = re.findall(r"\d+", normalized)
    canonical = (numeric_parts[-1].lstrip("0") or "0") if numeric_parts else re.sub(r"[^A-Z0-9]", "", normalized)
    digest = hmac.new(secret, b"raksha:v1:record-id\0" + namespace.encode() + b'\0' + canonical.encode(), hashlib.sha256).digest()
    return "REC-" + base64.b32encode(digest[:6]).decode().rstrip("=")


def _parse_age(raw: str) -> float | None:
    s = unicodedata.normalize("NFKC", raw).casefold()
    s = s.translate(str.maketrans("०१२३४५६७८९", "0123456789"))
    if re.search(r"\b(?:month|months|mo|mahine|mahina|महीने|माह)\b", s):
        m = re.search(r"\d+(?:\.\d+)?", s)
        return float(m.group()) / 12 if m else None
    if "decade" in s:
        approx = re.search(r"approx\s*(\d{1,3})", s)
        if approx:
            return float(approx.group(1))
        m = re.search(r"(\d+)\s*(?:1/2)?\s*decade", s)
        return (float(m.group(1)) + (0.5 if "1/2" in m.group(0) else 0)) * 10 if m else None
    if re.search(r"\bdob\b|birth", s):
        m = re.search(r"(?:19|20)\d{2}", s)
        return None  # A birth year needs an explicit encounter reference year.
    m = re.search(r"\d+(?:\.\d+)?", s)
    if not m:
        return None
    return float(m.group())


def generalize_age(raw: str, width: int = 5, top_code: int = 90, reference_year: int | None = None) -> str:
    birth_year = re.fullmatch(r'(?i)\s*DOB\s+(\d{4})\s*', raw)
    if birth_year and reference_year is not None:
        raw = str(reference_year - int(birth_year.group(1)))
    age_range = re.fullmatch(r'\s*(\d{1,3})\s*[-–]\s*(\d{1,3})\s*', raw)
    if age_range:
        low, high = map(int, age_range.groups())
        if low > high or high > 130:
            return '[AGE]'
        if low >= top_code:
            return f'{top_code}+'
        return f'{low // width * width}-{(high // width + 1) * width - 1}'
    age = _parse_age(raw)
    if age is None or age < 0 or age > 130:
        return "[AGE]"
    if age < 1:
        return "<1"
    if age >= top_code:
        return f"{top_code}+"
    lower = (int(age) // width) * width
    return f"{lower}-{lower + width - 1}"


def generalize_address(raw: str) -> str:
    """Drop household-level detail and retain only a coarse locality plus PIN prefix."""
    text = re.sub(
        r"(?i)\b(?:h\.?\s*no\.?|house\s*(?:no\.?)?|ward\s*(?:no\.?)?|mohalla|landmark)\b[^,;\n]*[,;\n]?",
        "", raw,
    )
    text = re.sub(r"(?<!\d)([1-8]\d{2})\s?(\d{3})(?!\d)", r"\1XXX", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;-\n")
    return text or "[ADDRESS]"


def _location_candidate(raw: str) -> str:
    """Return the coarsest locality/town visible without a gazetteer lookup."""
    text = generalize_address(raw)
    text = re.sub(r"(?<!\d)[1-8]\d{2}XXX(?!\d)", "", text).strip(" ,;-")
    parts = [part.strip() for part in re.split(r"[,;\n]", text) if part.strip()]
    if len(parts) > 1:
        return parts[-1]
    text = re.sub(r"(?i)^.*\b(?:mohalla|tola|bazar|ward)\b\s+", "", text).strip()
    text = re.sub(r"(?i)^\s*(?:vill(?:age)?\.?|town|city)\s+", "", text).strip()
    near = re.search(r"(?i)\bnear\s+(.+?)(?:\s+canal|\s+station|$)", text)
    return (near.group(1).strip() if near else text) or "[ADDRESS]"


def _location_outputs(records: Sequence[PatientRecord], k_location: int) -> dict[tuple[str, str], str]:
    """Choose one run-wide k-supported output for every address field."""
    candidate_patients: dict[str, set[str]] = {}
    raw_candidates: dict[tuple[str, str], str] = {}
    for rec in records:
        if rec.field_metadata.get("is_footer_row") or rec.field_metadata.get("is_empty_row"):
            continue
        patient = rec.pseudonym_id or rec.record_ref
        for node in rec.fields:
            if not node.raw_value or classify_field(node.header_key, [node.raw_value]) != "ADDRESS":
                continue
            candidate = _location_candidate(node.raw_value)
            key = unicodedata.normalize("NFKC", candidate).casefold()
            raw_candidates[(rec.record_ref, node.field_path)] = candidate
            candidate_patients.setdefault(key, set()).add(patient)
    return {
        record_path: candidate if len(candidate_patients[unicodedata.normalize("NFKC", candidate).casefold()]) >= k_location else "[ADDRESS]"
        for record_path, candidate in raw_candidates.items()
    }


def _id_token(raw: str) -> str:
    s = raw.upper()
    if re.search(r"\b(?:TATTOO(?:ED)?|SCAR|MOLE|BIRTHMARK|GOLD\s+TOOTH)\b", s):
        return "[ID_MARK]"
    if "AADHAAR" in s or "AADHAR" in s or re.fullmatch(r"[\d\s-]{12,20}", s):
        return "[AADHAAR]"
    if "ABHA" in s:
        return "[ABHA]"
    if re.search(r"\bPAN\b|[A-Z]{5}\d{4}[A-Z]", s):
        return "[PAN]"
    if re.search(r"\bDL\b|\b[A-Z]{2}\d{2}\s*\d{7,13}\b", s):
        return "[DL]"
    return "[CASE_NO]"


def _field_path(record: PatientRecord, index: int, header: str) -> str:
    return f"col:{index}:{header}" if record.loc.startswith("row:") else record.fields[index].field_path


def _whole(record: PatientRecord, path: str, value: str, transform: TransformType = TransformType.REDACT) -> PrivacyDecision:
    return PrivacyDecision(record_ref=record.record_ref, field_path=path, start=None, end=None,
                           transform_type=transform, replacement_value=value)


_EXTRA_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\b(?:aadhaar|aadhar)\b\s*[:#-]?\s*[\d\s-]{12,24}"), "[AADHAAR]"),
    (re.compile(r"(?i)\bDL\s*[A-Z]{0,2}\d{0,2}[\s-]*\d{7,13}\b"), "[DL]"),
    (re.compile(r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)"), "[IP]"),
    (re.compile(r"(?i)\b[A-Za-z0-9._-]+\\[A-Za-z0-9._-]+\b"), "[USERNAME]"),
    (re.compile(r"(?i)\b(?:MLC|FIR|GD|CASE)\s*(?:NO\.?)?\s*[A-Z0-9/-]+"), "[CASE_NO]"),
    (re.compile(r"(?i)\b(?:tattoo(?:ed)?|scar|mole|birthmark|gold\s+tooth)\b[^,;.]*"), "[ID_MARK]"),
    (re.compile(r"(?i)\bnot\s+the\s+[^,;.!?]+[.!?]?"), "[IDENTITY_HINT]"),
    (re.compile(r"(?i)\bno\s+relation\s+to\s+(?:Dr\.?\s+)?[A-Z][\w'-]+(?:\s+[A-Z][\w'-]+){0,3}[.!?]?"), "[IDENTITY_HINT]"),
    (re.compile(r"(?i)\bsame\s+family\s+as\s+[^,;(;.!?]+"), "[IDENTITY_HINT]"),
    (re.compile(
        r"(?i)(?:[;,.]\s*)?\b(?:oldest|youngest|first|only)\s+(?:patient|case)\b[^,;.!?]*|"
        r"(?:[;,.]\s*)?\b(?:pehla\s+case|sabse\s+buzurg|only\s+patient|famous|vip|celebrity)\b[^,;.!?]*|"
        r"(?:[;,.]\s*)?(?:पहला\s+मामला|सबसे\s+बुज़ुर्ग|एकमात्र\s+मरीज़)[^,;.!?]*"
    ), ""),
)


def _record_indexes(records: Sequence[PatientRecord], secret_key: bytes) -> dict[str, dict[str, str]]:
    """Map full encounter numbers and their numeric tails within each source file."""
    by_source: dict[str, dict[str, str]] = {}
    for rec in records:
        index = by_source.setdefault(rec.source_ref, {})
        for node in rec.fields:
            if not node.raw_value or classify_field(node.header_key, [node.raw_value]) != "RECORD_ID":
                continue
            token = _record_token(secret_key, node.raw_value, rec.field_metadata.get('record_namespace', ''))
            canonical = re.sub(r"\s+", "", unicodedata.normalize("NFKC", node.raw_value).casefold())
            index[canonical] = token
            digits = re.findall(r"\d+", node.raw_value)
            if digits:
                index[digits[-1].lstrip("0") or "0"] = token
    return by_source


def _record_tail_refs(records: Sequence[PatientRecord]) -> dict[str, dict[str, str]]:
    by_source: dict[str, dict[str, str]] = {}
    for rec in records:
        for node in rec.fields:
            if not node.raw_value or classify_field(node.header_key, [node.raw_value]) != "RECORD_ID":
                continue
            digits = re.findall(r"\d+", node.raw_value)
            if digits:
                by_source.setdefault(rec.source_ref, {})[digits[-1].lstrip("0") or "0"] = rec.record_ref
    return by_source


def _household_anchors(records: Sequence[PatientRecord], enabled: bool) -> dict[str, str]:
    anchors = {rec.record_ref: (rec.pseudonym_id or f"record:{rec.record_ref}") for rec in records}
    if not enabled:
        return anchors
    tail_refs = _record_tail_refs(records)
    for rec in records:
        text = " ".join(node.raw_value for node in rec.fields)
        if not re.search(r"(?i)\b(?:same\s+day|admitted\s+together|together)\b", text):
            continue
        for match in re.finditer(r"(?i)\b(?:IPD|OPD|UHID|MRN|reg(?:istration)?)\D{0,8}(\d{3,})\b", text):
            target = tail_refs.get(rec.source_ref, {}).get(match.group(1).lstrip("0") or "0")
            if target and target != rec.record_ref:
                household = "household:" + "|".join(sorted((rec.record_ref, target)))
                anchors[rec.record_ref] = household
                anchors[target] = household
    return anchors


def _date_for_limit(value: str, month_first: bool = False) -> datetime | None:
    stripped = value.strip()
    if re.fullmatch(r"\d{10}", stripped):
        return datetime.fromtimestamp(int(stripped), timezone.utc).replace(tzinfo=None)
    if re.fullmatch(r"\d{13}", stripped):
        return datetime.fromtimestamp(int(stripped) / 1000, timezone.utc).replace(tzinfo=None)
    if stripped.endswith("Z"):
        try:
            return datetime.fromisoformat(stripped[:-1] + "+00:00").replace(tzinfo=None)
        except ValueError:
            return None
    formats = (["%m/%d/%Y"] if month_first else []) + [
        "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d-%b-%y", "%d-%B-%y"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(stripped, fmt)
        except ValueError:
            pass
    return None


def _safe_date_offsets(
    records: Sequence[PatientRecord], secret_key: bytes, anchors: dict[str, str], max_days: int
) -> dict[str, int]:
    """Derive coherent offsets and deterministically clamp them before source/run dates."""
    input_dates = [parsed for rec in records for node in rec.fields
                   if (parsed := _date_for_limit(node.raw_value)) is not None]
    run_cap = max(input_dates, default=datetime(2000, 1, 1))
    source_caps: dict[str, datetime] = {}
    for rec in records:
        if not rec.field_metadata.get("is_footer_row"):
            continue
        text = " ".join(node.raw_value for node in rec.fields)
        found = re.search(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)", text)
        if found:
            parsed = _date_for_limit(found.group(1))
            if parsed:
                source_caps[rec.source_ref] = parsed

    latest_by_anchor: dict[str, datetime] = {}
    cap_by_anchor: dict[str, datetime] = {}
    for rec in records:
        anchor = anchors[rec.record_ref]
        cap_by_anchor[anchor] = min(cap_by_anchor.get(anchor, run_cap), source_caps.get(rec.source_ref, run_cap))
        record_text = " ".join(node.raw_value for node in rec.fields)
        month_first = bool(re.search(r"(?i)\bMM/DD\b", record_text)) or any(
            bool(re.fullmatch(r"\d{1,2}/(?:1[3-9]|2\d|3[01])/\d{4}", node.raw_value.strip()))
            for node in rec.fields
        )
        for node in rec.fields:
            if classify_field(node.header_key, [node.raw_value]) not in {"DATE", "DATETIME"}:
                continue
            parsed = _date_for_limit(node.raw_value, month_first)
            if parsed and parsed > latest_by_anchor.get(anchor, datetime.min):
                latest_by_anchor[anchor] = parsed

    offsets_by_anchor: dict[str, int] = {}
    for anchor in set(anchors.values()):
        offset = derive_date_offset(secret_key, anchor, max_days)
        latest = latest_by_anchor.get(anchor)
        cap = cap_by_anchor.get(anchor, run_cap)
        if latest and latest + timedelta(days=offset) > cap:
            for attempt in range(1, 10000):
                offset = derive_date_offset(secret_key, f"{anchor}:attempt:{attempt}", max_days)
                if latest + timedelta(days=offset) <= cap:
                    break
            else:
                raise ValueError("No date shift fits the permitted window")
        offsets_by_anchor[anchor] = offset
    return {record_ref: offsets_by_anchor[anchor] for record_ref, anchor in anchors.items()}


def _phonetic(value: str) -> str:
    s = unicodedata.normalize("NFKD", value.casefold()).encode("ascii", "ignore").decode()
    s = re.sub(r"\b(?:smt|shri|md|mohd|mr|mrs|ms)\.?\s+", "", s)
    s = s.replace("q", "k").replace("ee", "i")
    return re.sub(r"[^a-z]", "", s)


def _name_memory(records: Sequence[PatientRecord]) -> list[str]:
    names: list[str] = []
    for rec in records:
        if rec.field_metadata.get("is_footer_row") or rec.field_metadata.get("is_empty_row"):
            continue
        for node in rec.fields:
            role = classify_field(node.header_key, [node.raw_value]) if node.is_structured_key else "FREE_TEXT"
            if role != "PATIENT_NAME":
                continue
            raw = re.split(r"(?i)\s+(?:urf|alias|@)\s+", node.raw_value)[0]
            raw = re.sub(r"(?i)^\s*(?:smt|shri|md|mohd|mr|mrs|ms)\.?\s+", "", raw).strip()
            if raw and not raw.casefold().startswith("unknown"):
                names.append(raw)
                canonical = normalize_person_name(raw).canonical_name
                if canonical:
                    names.append(canonical)
                    parts = canonical.split()
                    if parts and len(parts[0]) >= 4 and parts[0].casefold() not in _KINSHIP_ONLY:
                        names.append(parts[0])
    return sorted(set(names), key=len, reverse=True)


def structure_aware_decisions(
    records: Sequence[PatientRecord], secret_key: bytes, *, age_width: int = 5,
    age_top_code: int = 90, date_shift_max_days: int = 180, k_location: int = 5,
    household_shift: bool = True,
) -> list[PrivacyDecision]:
    """Create schema-led decisions after pseudonym assignment and before serialization."""
    decisions: list[PrivacyDecision] = []
    memory = _name_memory(records)
    location_outputs = _location_outputs(records, k_location)
    hierarchy_entries = [(rec.record_ref, node.field_path, rec.pseudonym_id or rec.record_ref,
                          node.raw_value, _location_candidate(node.raw_value))
                         for rec in records for node in rec.fields
                         if (rec.record_ref, node.field_path) in location_outputs]
    hierarchy_results, hierarchy_aliases = hierarchy_outputs(hierarchy_entries, k_location)
    # Learn coarse PIN regions from the run. A region may be used only when
    # the source contains one unambiguous prefix; never invent geography.
    prefixes = {m.group(1) for rec in records for node in rec.fields
                if classify_field(node.header_key, [node.raw_value]) == "ADDRESS"
                for m in re.finditer(r"(?<!\d)([1-8]\d{2})\d{3}(?!\d)", node.raw_value)}
    regional_patients = {rec.pseudonym_id for rec in records if rec.pseudonym_id
                         and any(classify_field(n.header_key, [n.raw_value]) == "ADDRESS" for n in rec.fields)}
    region = next(iter(prefixes)) + "XXX region" if len(prefixes) == 1 and len(regional_patients) >= k_location else "[ADDRESS]"
    locality_map: dict[str, str] = {}
    for rec in records:
        for node in rec.fields:
            key = (rec.record_ref, node.field_path)
            if key not in location_outputs:
                continue
            candidate = _location_candidate(node.raw_value)
            nonlocal_text = bool(re.search(r"(?i)platform|railway|found near|canal", node.raw_value))
            if location_outputs[key] == "[ADDRESS]" and not nonlocal_text:
                location_outputs[key] = region
            if not nonlocal_text and candidate != "[ADDRESS]":
                locality_map[candidate] = location_outputs[key]
    # Explicit hierarchy evidence takes precedence over the legacy single-prefix
    # fallback. Preserve that fallback only for this otherwise unparented run.
    for key, output in hierarchy_results.items():
        if output != '[ADDRESS]':
            location_outputs[key] = output
    for alias, output in hierarchy_aliases.items():
        if output != '[ADDRESS]':
            locality_map[alias] = output
    record_indexes = _record_indexes(records, secret_key)
    household_anchors = _household_anchors(records, household_shift)
    safe_offsets = _safe_date_offsets(records, secret_key, household_anchors, date_shift_max_days)

    for rec in records:
        headers = list(rec.field_metadata.get("headers", []))
        values_by_header = {h: [] for h in headers}
        for node in rec.fields:
            values_by_header.setdefault(node.header_key, []).append(node.raw_value)

        date_offset = safe_offsets[rec.record_ref]
        record_text = " ".join(node.raw_value for node in rec.fields)
        month_first = bool(re.search(r"(?i)\bMM/DD\b", record_text)) or any(
            bool(re.fullmatch(r"\d{1,2}/(?:1[3-9]|2\d|3[01])/\d{4}", node.raw_value.strip()))
            for node in rec.fields
        )

        for idx, node in enumerate(rec.fields):
            raw = node.raw_value
            if any(
                span.field_path == f"@key:{node.field_path}" and span.is_header_detection
                for span in rec.detections
            ):
                decisions.append(_whole(rec, f"@key:{node.field_path}", sanitize_schema_label(node.header_key)))
            if not raw:
                continue
            role = classify_field(node.header_key, values_by_header.get(node.header_key, ())) if node.is_structured_key else "FREE_TEXT"
            path = node.field_path
            if rec.field_metadata.get('metadata_only'):
                if node.header_key.casefold() in {'login', 'machine', 'operator', 'username', 'host'}:
                    decisions.append(_whole(rec, path, '[USERNAME]'))
                    continue
                if role == 'PATIENT_NAME':
                    decisions.append(_whole(rec, path, '[RELATIVE]'))
                    continue
            if node.header_key.casefold() in {'school', 'occupation'}:
                decisions.append(_whole(rec, path, '[' + node.header_key.upper() + ']'))
                continue
            for locality, replacement in locality_map.items():
                for mention in re.finditer(re.escape(locality), raw, re.IGNORECASE):
                    decisions.append(PrivacyDecision(rec.record_ref, path, mention.start(), mention.end(),
                                                     TransformType.GENERALIZE, replacement))
            if rec.field_metadata.get("is_footer_row"):
                role = "FREE_TEXT"
            if rec.field_metadata.get("is_empty_row"):
                continue
            if role == "PATIENT_NAME":
                decisions.append(_whole(rec, path, rec.pseudonym_id or "[PATIENT]", TransformType.PSEUDONYMIZE))
                continue
            if role == "PHONE":
                decisions.append(_whole(rec, path, "[PHONE]"))
                continue
            if role == "ID_DOC":
                decisions.append(_whole(rec, path, _id_token(raw)))
                continue
            if role == "RECORD_ID":
                decisions.append(_whole(rec, path, _record_token(secret_key, raw, rec.field_metadata.get('record_namespace', '')), TransformType.PSEUDONYMIZE))
                continue
            if role in {"AGE", "AGE_DOB"}:
                years = [d.year for n in rec.fields
                         if classify_field(n.header_key) in {'DATE', 'DATETIME'}
                         and (d := _date_for_limit(n.raw_value)) is not None]
                decisions.append(_whole(rec, path, generalize_age(raw, age_width, age_top_code,
                                                               min(years) if years else None), TransformType.GENERALIZE))
                continue
            if role == "ADDRESS":
                decisions.append(_whole(
                    rec, path,
                    location_outputs.get((rec.record_ref, path), "[ADDRESS]"),
                    TransformType.GENERALIZE,
                ))
                continue
            if role in {"DATE", "DATETIME", "DOB"}:
                try:
                    shifted = shift_any_date(raw, date_offset, month_first=month_first)
                except ValueError:
                    shifted = "[DATE]"
                decisions.append(_whole(rec, path, shifted, TransformType.DATE_SHIFT))
                continue
            if role == "RELATIVE":
                low_words = set(re.findall(r"[A-Za-z]+", raw.casefold()))
                if low_words and low_words <= (_KINSHIP_ONLY | {"guardian", "naam", "nahi", "bataya"}):
                    decisions.append(_whole(rec, path, raw, TransformType.GENERALIZE))
                    continue
                rel = re.sub(
                    r"(?i)(\b(?:s/o|d/o|w/o|h/o|c/o|husband\s+of|wife\s+of|father\s+of|mother\s+of|widow\s+of(?:\s+late)?(?:\s+shri)?)\b)\s+[^,;()]*?\S(?=\s*[,;()]|$)",
                    r"\1 [RELATIVE]", raw,
                )
                staff = re.sub(
                    r"(?i)(\b(?:EMT|Sr\.|Sister|Nurse|Ct\.|Constable|clerk)\s+)[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2}",
                    r"\1[STAFF]", rel,
                )
                for locality, replacement in locality_map.items():
                    staff = re.sub(re.escape(locality), replacement, staff, flags=re.IGNORECASE)
                decisions.append(_whole(rec, path, staff if staff != raw else "[RELATIVE]"))
                continue

            # Typed spans in narrative, diagnostic and footer fields.
            for pattern, token in _EXTRA_PATTERNS:
                for match in pattern.finditer(raw):
                    decisions.append(PrivacyDecision(rec.record_ref, path, match.start(), match.end(),
                                                     TransformType.REDACT, token))

            if rec.field_metadata.get("is_footer_row"):
                for match in re.finditer(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", raw):
                    decisions.append(PrivacyDecision(
                        rec.record_ref, path, match.start(), match.end(),
                        TransformType.REDACT, "[DATE]",
                    ))

            # Stable record references anywhere in narrative text.
            for match in re.finditer(r"(?i)\b(?:IPD|OPD|UHID|MRN|SDH)\s*(?:NO\.?)?\s*[A-Z0-9/-]*\d[A-Z0-9/-]*", raw):
                decisions.append(PrivacyDecision(rec.record_ref, path, match.start(), match.end(),
                                                 TransformType.PSEUDONYMIZE,
                                                 _record_token(secret_key, match.group(), rec.field_metadata.get('record_namespace', ''))))

            # Bare numeric tails are identifiers only near record-reference
            # language and only when the same file declared that encounter.
            source_index = record_indexes.get(rec.source_ref, {})
            for match in re.finditer(
                r"(?i)\b(?:ignore|duplicate|dup\s+of|see|same\s+as|IPD|reg(?:istration)?|entry|row|#)\b"
                r"[^\d\n]{0,18}(\d{3,})\b",
                raw,
            ):
                tail = match.group(1).lstrip("0") or "0"
                token = source_index.get(tail)
                if token:
                    decisions.append(PrivacyDecision(
                        rec.record_ref, path, match.start(1), match.end(1),
                        TransformType.PSEUDONYMIZE, token,
                    ))

            # Per-run full-name sweep, including common transliteration spellings.
            word_matches = list(re.finditer(r"[A-Za-z][A-Za-z.']*", raw))
            for known in memory:
                count = len(known.split())
                if count < 1:
                    continue
                for pos in range(0, len(word_matches) - count + 1):
                    group = word_matches[pos : pos + count]
                    ctext = raw[group[0].start() : group[-1].end()]
                    if _phonetic(ctext) == _phonetic(known):
                        decisions.append(PrivacyDecision(rec.record_ref, path, group[0].start(), group[-1].end(),
                                                         TransformType.REDACT, "[PATIENT]"))

            # Staff cues are redacted, but doctors deliberately remain useful.
            for match in re.finditer(
                r"(?i)(?<!Dr\.\s)\b(?:EMT|Sr\.|Sister|Nurse|Ct\.|Constable|clerk|Printed\s+by|Exported\s+by|verified\s+by|Typed\s+by)\s*:?\s+[A-Z][\w.-]*(?:\s+[A-Z][\w.-]*){0,2}", raw
            ):
                decisions.append(PrivacyDecision(rec.record_ref, path, match.start(), match.end(),
                                                 TransformType.REDACT, "[STAFF]"))

        # Existing detector results still get safe typed tokens when not otherwise covered.
        for span in rec.detections:
            if (
                span.role == SpanRole.QUASI_IDENTIFIER
                and span.category.upper() in {
                    "DATE", "VISIT_DATE", "ADMISSION_DATE", "DISCHARGE_DATE", "DOB",
                    "DATE_OF_BIRTH", "TEXT_DATE",
                }
            ):
                field = next((node for node in rec.fields if node.field_path == span.field_path), None)
                if field is not None and span.end <= len(field.raw_value):
                    try:
                        shifted = shift_any_date(
                            field.raw_value[span.start:span.end], date_offset, month_first=month_first
                        )
                    except ValueError:
                        shifted = "[DATE]"
                    decisions.append(PrivacyDecision(
                        rec.record_ref, span.field_path, span.start, span.end,
                        TransformType.DATE_SHIFT, shifted,
                    ))
                continue
            if span.role != SpanRole.DIRECT_PII:
                continue
            if span.is_header_detection or span.field_path.startswith(("@header:", "@key:")):
                continue
            if span.category.upper() in {"UHID", "MRN", "PATIENT_IDENTIFIER"}:
                continue
            decisions.append(PrivacyDecision(rec.record_ref, span.field_path, span.start, span.end,
                                             TransformType.REDACT, typed_token(span.category)))
    return decisions


def shift_any_date(value: str, offset_days: int, *, month_first: bool = False) -> str:
    """Shift common hospital date encodings while retaining their input representation."""
    stripped = value.strip()
    if month_first and re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", stripped):
        parsed = datetime.strptime(stripped, "%m/%d/%Y")
        return (parsed + timedelta(days=offset_days)).strftime("%m/%d/%Y")
    try:
        return shift_date_value(value, offset_days)
    except ValueError:
        pass
    for fmt in ("%d-%b-%y", "%d-%B-%y", "%d %b %Y", "%m/%d/%Y"):
        try:
            parsed = datetime.strptime(stripped, fmt)
        except ValueError:
            continue
        return (parsed + timedelta(days=offset_days)).strftime(fmt)
    if re.fullmatch(r"\d{10}", stripped):
        return str(int((datetime.fromtimestamp(int(stripped), timezone.utc) + timedelta(days=offset_days)).timestamp()))
    if re.fullmatch(r"\d{13}", stripped):
        return str(int((datetime.fromtimestamp(int(stripped) / 1000, timezone.utc) + timedelta(days=offset_days)).timestamp() * 1000))
    raise ValueError("Unsupported or invalid date value")
