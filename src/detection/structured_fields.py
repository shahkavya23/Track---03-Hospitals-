# Purpose: Token-semantic structured field classifier, FHIR resource mapper, and header/key PII detector.
"""Structured field label, FHIR path, and header/key PII detection."""

from __future__ import annotations

import re

from src.contracts import DetectionSpan, FieldNode, PatientRecord, SpanRole
from src.detection.normalization import (
    normalize_date,
    normalize_person_name,
    normalize_phone,
    normalize_with_offset_map,
)

from .regex_rules import detect_regex_candidates

_NULL_LIKE = frozenset({"", "n/a", "na", "none", "null", "-", "--", "---", "unknown"})

# Semantic token sets used to classify arbitrary unseen column headers (camelCase/snake_case/Hindi).
_CLINICIAN_TOKENS = frozenset({
    "doctor", "dr", "physician", "clinician", "surgeon", "consultant",
    "prescriber", "practitioner", "doc", "चिकित्सक", "डॉक्टर",
})
_RELATIVE_TOKENS = frozenset({
    "relative", "guardian", "father", "mother", "spouse", "husband",
    "wife", "kin", "nok", "emergency", "parent", "care",
    "अभिभावक", "पिता", "पति", "पत्नी", "माता",
})
_FACILITY_TOKENS = frozenset({
    "facility", "hospital", "hosp", "clinic", "center", "centre",
    "institute", "ward", "department", "dept", "issuer", "अस्पताल",
})
_NAME_TOKENS = frozenset({
    "name", "nm", "fullname", "given", "family", "surname", "first", "last", "middle", "नाम",
})
_PATIENT_TOKENS = frozenset({
    "patient", "pt", "beneficiary", "subject", "client", "मरीज", "रोगी",
})
_PHONE_TOKENS = frozenset({
    "phone", "ph", "mob", "mobile", "contact", "tel", "telephone", "cell", "whatsapp", "फोन", "मोबाइल",
})
_EMAIL_TOKENS = frozenset({"email", "mail"})
_AADHAAR_TOKENS = frozenset({"aadhaar", "aadhar", "uid", "uidai", "आधार"})
_ABHA_TOKENS = frozenset({"abha", "ndhm", "abdm", "ayushman", "healthid"})
_PAN_TOKENS = frozenset({"pan", "pancard", "पैन"})
_MRN_TOKENS = frozenset({"mrn", "mr"})
_UHID_TOKENS = frozenset({"uhid", "ipd", "opd", "reg", "regn", "registration", "emr", "cr"})
_INSURANCE_TOKENS = frozenset({"insurance", "policy", "tpa", "बीमा"})
_ADDRESS_TOKENS = frozenset({"address", "addr", "street", "residence", "res", "locality", "पता", "निवासी"})
_DOB_TOKENS = frozenset({"dob", "birth", "birthdate", "born", "जन्म"})
_DOA_TOKENS = frozenset({"admit", "admission", "adm", "doa", "भर्ती"})
_DOD_TOKENS = frozenset({"discharge", "disch", "dod", "छुट्टी"})
_VISIT_DATE_TOKENS = frozenset({"visit", "encounter", "appt", "appointment", "consult", "date", "dt", "दिनांक", "तारीख"})
_AGE_TOKENS = frozenset({"age", "उम्र", "आयु"})
_PIN_TOKENS = frozenset({"pin", "pincode", "postal", "postalcode", "zip", "पिन"})
_VILLAGE_TOKENS = frozenset({"village", "vill", "gram", "town", "city", "tehsil", "taluka", "ग्राम", "गांव", "शहर"})
_DISTRICT_TOKENS = frozenset({"district", "dist", "जिला"})
_STATE_TOKENS = frozenset({"state", "province", "राज्य"})
_GENDER_TOKENS = frozenset({"gender", "sex", "लिंग"})

_SAFE_SCHEMA_TOKENS = (
    _CLINICIAN_TOKENS | _RELATIVE_TOKENS | _FACILITY_TOKENS | _NAME_TOKENS | _PATIENT_TOKENS
    | _PHONE_TOKENS | _EMAIL_TOKENS | _AADHAAR_TOKENS | _ABHA_TOKENS | _PAN_TOKENS
    | _MRN_TOKENS | _UHID_TOKENS | _INSURANCE_TOKENS | _ADDRESS_TOKENS | _DOB_TOKENS
    | _DOA_TOKENS | _DOD_TOKENS | _VISIT_DATE_TOKENS | _AGE_TOKENS | _PIN_TOKENS
    | _VILLAGE_TOKENS | _DISTRICT_TOKENS | _STATE_TOKENS | _GENDER_TOKENS
    | {
        "no", "num", "number", "id", "card", "yrs", "years", "code", "status", "type",
        "use", "value", "system", "display", "text", "div", "data", "attachment",
        "notes", "note", "clinical", "diagnosis", "dx", "diagnoses", "condition",
        "medication", "medications", "meds", "dosage", "dose", "vitals", "lab",
        "result", "procedure", "procedures", "complaint", "complaints", "chief",
        "history", "assessment", "plan", "impression", "rx", "prescription",
        "resourcetype", "entry", "resource", "telecom", "reference", "fullurl",
        "period", "start", "end", "doc", "visits", "records", "line", "full",
        "curr", "current", "perm", "permanent", "alt", "alternate", "home", "ref", "by",
        "treated", "treating", "attending", "referring", "primary", "secondary",
        "overflow",
    }
)

_AGE_INT_RE = re.compile(r"\b(\d{1,3})\b")
_FHIR_NUMERIC_SHIFT_FORMATS = re.compile(
    r"^\s*(?:\d{4}-\d{2}-\d{2}(?:T.*)?|\d{2}/\d{2}/\d{4}|\d{2}-\d{2}-\d{4}|\d{4}/\d{2}/\d{2})\s*$"
)
_URI_OR_REF_RE = re.compile(
    r"^(?:https?://|urn:|Patient/|Practitioner/|Observation/|Condition/|Encounter/)",
    re.IGNORECASE,
)


def _header_tokens(header_key: str) -> tuple[str, ...]:
    """Split snake_case, kebab-case, camelCase, and spaced headers into semantic tokens."""
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", header_key.strip())
    parts = [p.lower() for p in re.split(r"[\s_\-./:]+", camel_split) if p]
    return tuple(parts)


def infer_record_facility_issuer(record: PatientRecord) -> str:
    """Safely derive an internal facility/hospital issuer code for local ID namespacing."""
    for node in record.fields:
        if not node.is_structured_key:
            continue
        toks = set(_header_tokens(node.header_key))
        if toks & _FACILITY_TOKENS and not (toks & _PATIENT_TOKENS):
            val = re.sub(r"[^A-Z0-9]+", "_", node.raw_value.strip().upper()).strip("_")
            if val:
                return val[:32]
    return "UNKNOWN_HOSPITAL"


def _header_contains_pii(header_key: str) -> bool:
    """Detect whether a column header or JSON key itself embeds PII (email, phone, ID, name)."""
    stripped = header_key.strip()
    if not stripped or stripped.startswith("__overflow_"):
        return False

    toks = _header_tokens(stripped)
    if toks and all(t in _SAFE_SCHEMA_TOKENS or t.isdigit() for t in toks):
        return False

    space_key = re.sub(r"[_]+", " ", stripped)
    if detect_regex_candidates(space_key):
        return True

    # Detect embedded proper-noun personal names inside keys (e.g., "patient_rahul_verma_id").
    tok_set = set(toks)
    non_schema = [t for t in toks if t not in _SAFE_SCHEMA_TOKENS and len(t) >= 3 and t.isalpha()]
    if (tok_set & (_PATIENT_TOKENS | _RELATIVE_TOKENS | {"mr", "mrs", "ms", "smt", "shri"})) and len(non_schema) >= 2:
        return True
    return False


def build_fhir_resource_map(record: PatientRecord) -> dict[str, str]:
    """Map FHIR JSON pointer resource prefixes (e.g. '/entry/1/resource') to resourceType."""
    resource_map: dict[str, str] = {}
    for node in record.fields:
        if node.is_structured_key and node.header_key == "resourceType" and node.raw_value.strip():
            fp = node.field_path
            if fp == "/resourceType":
                resource_map[""] = node.raw_value.strip()
            elif fp.endswith("/resourceType"):
                resource_map[fp[: -len("/resourceType")]] = node.raw_value.strip()
    return resource_map


def _fhir_resource_role_hint(
    field_path: str,
    fhir_resource_map: dict[str, str] | None = None,
) -> str | None:
    """Infer semantic entity role from FHIR R4 resourceType prefix and pointer path."""
    fp = field_path.lower()
    if not fp.startswith("/"):
        return None
    if "/practitioner" in fp or "/participant/" in fp or "/performer" in fp or "/requester" in fp:
        return "CLINICIAN"
    if "/organization" in fp:
        return "FACILITY"

    if fhir_resource_map:
        best_prefix = ""
        best_rtype = ""
        for prefix, rtype in fhir_resource_map.items():
            if (prefix == "" or field_path.startswith(prefix + "/")) and len(prefix) >= len(best_prefix):
                best_prefix = prefix
                best_rtype = rtype.lower()
        if best_rtype == "practitioner":
            return "CLINICIAN"
        if best_rtype in {"organization", "location"}:
            return "FACILITY"
        if best_rtype == "patient":
            if "/contact/" in fp:
                return "RELATIVE"
            return "PATIENT"

    if "/patient" in fp:
        if "/contact/" in fp:
            return "RELATIVE"
        return "PATIENT"
    return None


def _add_attr(record: PatientRecord, key: str, value: str) -> None:
    cleaned = value.strip()
    if not cleaned:
        return
    bucket = record.extracted_patient_attributes.setdefault(key, [])
    if cleaned not in bucket:
        bucket.append(cleaned)


def analyze_structured_field(
    record: PatientRecord,
    node: FieldNode,
    issuer: str,
    fhir_resource_map: dict[str, str] | None = None,
) -> list[DetectionSpan]:
    """Analyze one structured `FieldNode` using token-semantic header classification."""
    spans: list[DetectionSpan] = []

    if node.is_structured_key and _header_contains_pii(node.header_key):
        if node.field_path.startswith("col:"):
            col_parts = node.field_path.split(":", 2)
            header_target = f"@header:{col_parts[1]}" if len(col_parts) >= 2 else f"@header:{node.header_key}"
        else:
            header_target = f"@key:{node.field_path}"
        spans.append(
            DetectionSpan(
                record_ref=record.record_ref,
                field_path=header_target,
                start=0,
                end=len(node.header_key),
                category="HEADER_PII" if node.field_path.startswith("col:") else "KEY_PII",
                role=SpanRole.DIRECT_PII,
                confidence=0.92,
                detector_source="structured_header_pii",
                is_header_detection=True,
            )
        )

    raw = node.raw_value
    if not raw or raw.strip().lower() in _NULL_LIKE or not node.is_structured_key:
        return spans

    fp_lower = node.field_path.lower()
    toks = _header_tokens(node.header_key)
    tok_set = set(toks)
    if tok_set & {"resourcetype", "system", "code", "status", "use", "reference", "fullurl"} and len(toks) == 1:
        return spans
    if _URI_OR_REF_RE.match(raw.strip()) and not (tok_set & _EMAIL_TOKENS):
        return spans

    lead = len(raw) - len(raw.lstrip())
    trail = len(raw.rstrip())
    if lead >= trail:
        return spans

    fhir_hint = _fhir_resource_role_hint(node.field_path, fhir_resource_map)
    safe_issuer = re.sub(r"[^A-Z0-9_]", "_", issuer.upper()).strip("_") or "UNKNOWN_HOSPITAL"

    # 1. FHIR path-specific role classification
    if fhir_hint == "CLINICIAN" and ((tok_set & _NAME_TOKENS) or "/name/" in fp_lower):
        spans.append(
            DetectionSpan(
                record_ref=record.record_ref,
                field_path=node.field_path,
                start=lead,
                end=trail,
                category="CLINICIAN_NAME",
                role=SpanRole.STAFF_OR_FACILITY,
                confidence=0.98,
                detector_source="structured_fhir_clinician",
            )
        )
        return spans

    if fhir_hint == "FACILITY" and (tok_set & {"name", "text"}):
        spans.append(
            DetectionSpan(
                record_ref=record.record_ref,
                field_path=node.field_path,
                start=lead,
                end=trail,
                category="FACILITY_NAME",
                role=SpanRole.STAFF_OR_FACILITY,
                confidence=0.97,
                detector_source="structured_fhir_facility",
            )
        )
        return spans

    if fhir_hint == "RELATIVE" and ((tok_set & _NAME_TOKENS) or "/name/" in fp_lower):
        norm_rel = normalize_person_name(raw)
        if norm_rel.name_key:
            _add_attr(record, "relative_name_keys", norm_rel.name_key)
        spans.append(
            DetectionSpan(
                record_ref=record.record_ref,
                field_path=node.field_path,
                start=lead,
                end=trail,
                category="RELATIVE_NAME",
                role=SpanRole.DIRECT_PII,
                confidence=0.97,
                detector_source="structured_fhir_relative",
            )
        )
        return spans

    # 2. Token-semantic classification (handles unseen headers like "ref_by_dr", "alt_mob_num", "pt_dob")
    has_id_token = bool(tok_set & {"id", "no", "num", "number", "card"})

    if (tok_set & _CLINICIAN_TOKENS) and not (tok_set & (_PHONE_TOKENS | _EMAIL_TOKENS)):
        spans.append(
            DetectionSpan(
                record_ref=record.record_ref,
                field_path=node.field_path,
                start=lead,
                end=trail,
                category="CLINICIAN_NAME",
                role=SpanRole.STAFF_OR_FACILITY,
                confidence=0.97,
                detector_source="structured_clinician",
            )
        )
        return spans

    if (tok_set & _FACILITY_TOKENS) and not (tok_set & (_PATIENT_TOKENS | _UHID_TOKENS | _MRN_TOKENS)):
        spans.append(
            DetectionSpan(
                record_ref=record.record_ref,
                field_path=node.field_path,
                start=lead,
                end=trail,
                category="FACILITY_NAME",
                role=SpanRole.STAFF_OR_FACILITY,
                confidence=0.96,
                detector_source="structured_facility",
            )
        )
        return spans

    if (tok_set & _RELATIVE_TOKENS) and not (tok_set & (_PHONE_TOKENS | _EMAIL_TOKENS | _ADDRESS_TOKENS)):
        norm_rel = normalize_person_name(raw)
        if norm_rel.name_key:
            _add_attr(record, "relative_name_keys", norm_rel.name_key)
        spans.append(
            DetectionSpan(
                record_ref=record.record_ref,
                field_path=node.field_path,
                start=lead,
                end=trail,
                category="RELATIVE_NAME",
                role=SpanRole.DIRECT_PII,
                confidence=0.96,
                detector_source="structured_relative_name",
            )
        )
        return spans

    if ((tok_set & _NAME_TOKENS) or (tok_set == {"patient"}) or (fhir_hint == "PATIENT" and (tok_set & {"given", "family", "text"}))) and not has_id_token:
        norm_name = normalize_person_name(raw)
        if norm_name.canonical_name:
            _add_attr(record, "names", norm_name.canonical_name)
        if norm_name.name_key:
            _add_attr(record, "name_keys", norm_name.name_key)
        spans.append(
            DetectionSpan(
                record_ref=record.record_ref,
                field_path=node.field_path,
                start=lead,
                end=trail,
                category="PATIENT_NAME",
                role=SpanRole.DIRECT_PII,
                confidence=0.97,
                detector_source="structured_patient_name",
            )
        )
        return spans

    if (tok_set & _PHONE_TOKENS) or ("/telecom/" in fp_lower and "value" in tok_set and "@" not in raw):
        parsed_phone = normalize_phone(raw)
        if parsed_phone is not None:
            _add_attr(record, "phones", parsed_phone.e164)
            spans.append(
                DetectionSpan(
                    record_ref=record.record_ref,
                    field_path=node.field_path,
                    start=lead,
                    end=trail,
                    category="PHONE",
                    role=SpanRole.DIRECT_PII,
                    confidence=0.99,
                    detector_source="structured_phone",
                )
            )
            return spans

    if (tok_set & _EMAIL_TOKENS) or ("/telecom/" in fp_lower and "value" in tok_set and "@" in raw):
        if "@" in raw:
            cat = "ABHA" if re.search(r"@(?:abdm|ndhm|sbx)\b", raw, re.I) else "EMAIL"
            if cat == "ABHA":
                _add_attr(record, "ids", f"ABHA|{raw.strip().lower()}")
            spans.append(
                DetectionSpan(
                    record_ref=record.record_ref,
                    field_path=node.field_path,
                    start=lead,
                    end=trail,
                    category=cat,
                    role=SpanRole.DIRECT_PII,
                    confidence=0.99,
                    detector_source="structured_email",
                )
            )
            return spans

    if tok_set & _AADHAAR_TOKENS:
        digits = re.sub(r"\D", "", normalize_with_offset_map(raw).normalized)
        if len(digits) == 12:
            _add_attr(record, "ids", f"AADHAAR|{digits}")
        spans.append(
            DetectionSpan(
                record_ref=record.record_ref,
                field_path=node.field_path,
                start=lead,
                end=trail,
                category="AADHAAR",
                role=SpanRole.DIRECT_PII,
                confidence=0.98,
                detector_source="structured_aadhaar",
            )
        )
        return spans

    if tok_set & _ABHA_TOKENS:
        digits = re.sub(r"\D", "", normalize_with_offset_map(raw).normalized)
        if len(digits) == 14:
            _add_attr(record, "ids", f"ABHA|{digits}")
        elif "@" in raw:
            _add_attr(record, "ids", f"ABHA|{raw.strip().lower()}")
        spans.append(
            DetectionSpan(
                record_ref=record.record_ref,
                field_path=node.field_path,
                start=lead,
                end=trail,
                category="ABHA",
                role=SpanRole.DIRECT_PII,
                confidence=0.98,
                detector_source="structured_abha",
            )
        )
        return spans

    if tok_set & _PAN_TOKENS:
        val = normalize_with_offset_map(raw).normalized.strip().upper()
        if re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", val):
            _add_attr(record, "ids", f"PAN|{val}")
        spans.append(
            DetectionSpan(
                record_ref=record.record_ref,
                field_path=node.field_path,
                start=lead,
                end=trail,
                category="PAN",
                role=SpanRole.DIRECT_PII,
                confidence=0.98,
                detector_source="structured_pan",
            )
        )
        return spans

    if (tok_set & (_UHID_TOKENS | _MRN_TOKENS | _INSURANCE_TOKENS)) or (
        (tok_set & _PATIENT_TOKENS) and has_id_token
    ) or (tok_set == {"id"} and fhir_hint == "PATIENT"):
        norm_val = normalize_with_offset_map(raw).normalized.strip().upper()
        if tok_set & _MRN_TOKENS:
            cat, id_type = "MRN", "MRN"
        elif tok_set & _INSURANCE_TOKENS:
            cat, id_type = "INSURANCE_ID", "INSURANCE"
        elif (tok_set & _PATIENT_TOKENS) and has_id_token:
            cat, id_type = "PATIENT_IDENTIFIER", "UHID"
        else:
            cat, id_type = "UHID", "UHID"
        _add_attr(record, "ids", f"{id_type}|{safe_issuer}|{norm_val}")
        spans.append(
            DetectionSpan(
                record_ref=record.record_ref,
                field_path=node.field_path,
                start=lead,
                end=trail,
                category=cat,
                role=SpanRole.DIRECT_PII,
                confidence=0.97,
                detector_source="structured_local_id",
            )
        )
        return spans

    if (tok_set & _ADDRESS_TOKENS) or ("/address/" in fp_lower and bool(tok_set & {"line", "text"})):
        spans.append(
            DetectionSpan(
                record_ref=record.record_ref,
                field_path=node.field_path,
                start=lead,
                end=trail,
                category="ADDRESS",
                role=SpanRole.DIRECT_PII,
                confidence=0.96,
                detector_source="structured_address",
            )
        )
        return spans

    if tok_set & (_DOB_TOKENS | _DOA_TOKENS | _DOD_TOKENS | _VISIT_DATE_TOKENS):
        parsed_date = normalize_date(raw)
        if parsed_date is not None:
            if tok_set & _DOB_TOKENS:
                if parsed_date.iso_date:
                    _add_attr(record, "dobs", parsed_date.iso_date)
                _add_attr(record, "birth_years", parsed_date.year)
                date_cat = "DOB"
            elif tok_set & _DOA_TOKENS:
                _add_attr(record, "visit_years", parsed_date.year)
                date_cat = "ADMISSION_DATE"
            elif tok_set & _DOD_TOKENS:
                _add_attr(record, "visit_years", parsed_date.year)
                date_cat = "DISCHARGE_DATE"
            else:
                _add_attr(record, "visit_years", parsed_date.year)
                date_cat = "VISIT_DATE"

            if not _FHIR_NUMERIC_SHIFT_FORMATS.match(raw):
                date_cat = "TEXT_DATE"
            spans.append(
                DetectionSpan(
                    record_ref=record.record_ref,
                    field_path=node.field_path,
                    start=lead,
                    end=trail,
                    category=date_cat,
                    role=SpanRole.QUASI_IDENTIFIER,
                    confidence=0.98,
                    detector_source="structured_date",
                )
            )
            return spans

    if tok_set & _AGE_TOKENS:
        indexed = normalize_with_offset_map(raw)
        m = _AGE_INT_RE.search(indexed.normalized)
        if m:
            age_val = int(m.group(1))
            if 0 <= age_val <= 125:
                s, e = indexed.to_original_span(m.start(1), m.end(1))
                if raw[s:e].strip().isascii() and raw[s:e].strip().isdigit():
                    _add_attr(record, "ages", str(age_val))
                    spans.append(
                        DetectionSpan(
                            record_ref=record.record_ref,
                            field_path=node.field_path,
                            start=s,
                            end=e,
                            category="AGE",
                            role=SpanRole.QUASI_IDENTIFIER,
                            confidence=0.97,
                            detector_source="structured_age",
                        )
                    )
                    return spans

    if (tok_set & _PIN_TOKENS) or ("/address/" in fp_lower and "postalcode" in tok_set):
        digits = re.sub(r"\D", "", normalize_with_offset_map(raw).normalized)
        if len(digits) == 6:
            _add_attr(record, "geo_keys", f"PIN_{digits[:3]}")
            spans.append(
                DetectionSpan(
                    record_ref=record.record_ref,
                    field_path=node.field_path,
                    start=lead,
                    end=trail,
                    category="PIN_CODE",
                    role=SpanRole.QUASI_IDENTIFIER,
                    confidence=0.97,
                    detector_source="structured_pin",
                )
            )
            return spans

    if (tok_set & (_VILLAGE_TOKENS | _DISTRICT_TOKENS | _STATE_TOKENS)) or (
        "/address/" in fp_lower and bool(tok_set & {"city", "district", "state"})
    ):
        clean_geo = normalize_with_offset_map(raw).normalized.strip()
        if clean_geo:
            _add_attr(record, "geo_keys", clean_geo.lower())
            if tok_set & _DISTRICT_TOKENS or "city" in tok_set:
                _add_attr(record, "districts", clean_geo)
            elif tok_set & _STATE_TOKENS:
                _add_attr(record, "states", clean_geo)
            spans.append(
                DetectionSpan(
                    record_ref=record.record_ref,
                    field_path=node.field_path,
                    start=lead,
                    end=trail,
                    category="VILLAGE" if (tok_set & _VILLAGE_TOKENS) else "LOCATION",
                    role=SpanRole.QUASI_IDENTIFIER,
                    confidence=0.95,
                    detector_source="structured_geo",
                )
            )
            return spans

    if tok_set & _GENDER_TOKENS:
        g = raw.strip().upper()[:1]
        if g in {"M", "F", "O"}:
            _add_attr(record, "genders", g)
        return spans

    return spans
