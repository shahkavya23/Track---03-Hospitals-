# Purpose: Grammatical & structural multilingual context rules (no sample-word hardcoding).
"""Multilingual context rules using grammatical boundaries and clinical disambiguation."""

from __future__ import annotations

from dataclasses import dataclass
import re

from src.clinical.conditions import is_clinical_complaint_phrase
from src.contracts import SpanRole
from src.detection.normalization import (
    IndexedText,
    normalize_person_name,
    normalize_with_offset_map,
)

# Structural grammatical boundaries (NOT sample-sentence stopwords):
# - English/Latin field labels & uppercase clinical acronyms
_LATIN_NON_NAME_WORDS = frozenset({
    "patient", "pt", "name", "age", "sex", "male", "female", "dob", "doa", "dod",
    "address", "phone", "mobile", "uhid", "mrn", "abha", "aadhaar", "aadhar", "pan",
    "opd", "ipd", "icu", "ecg", "usg", "mri", "ct", "bp", "hr", "pr", "rr", "spo2",
    "temp", "tlc", "cbc", "lft", "kft", "rft", "uti", "cad", "ckd", "copd", "htn",
    "t2dm", "dm", "tb", "hiv", "cabg", "ptca", "pci", "lscs", "pin", "doctor", "dr",
    "disease", "syndrome", "lymphoma", "palsy", "thyroiditis", "phenomenon", "spine",
    "arteritis", "score", "scale", "triad", "sign", "reflex", "fracture",
    "tab", "cap", "inj", "syp", "susp", "oint", "drops", "neb", "rx", "dx",
})

# Hindi grammatical postpositions, auxiliaries, conjunctions, and demographic field markers
# that universally terminate a Devanagari person-name phrase.
_DEVA_GRAMMAR_BOUNDARIES = frozenset({
    "को", "का", "की", "के", "ने", "से", "में", "पर", "तक", "द्वारा", "हेतु", "लिए",
    "है", "हैं", "था", "थे", "थी", "थीं", "हुआ", "हुई", "हुए", "गया", "गई", "गए",
    "दिया", "दी", "दिए", "लिया", "ली", "और", "व", "एवं", "तथा", "या", "जो",
    "उम्र", "आयु", "पता", "फोन", "मोबाइल", "निवासी", "पुत्र", "पुत्री", "पत्नी",
    "पति", "पिता", "माता", "अभिभावक", "मरीज", "रोगी", "डॉक्टर", "डॉ", "दिनांक",
    "तारीख", "जन्म", "भर्ती", "छुट्टी", "जी", "साहब", "साहिब", "दवा", "इलाज",
})

# Short lowercase name connectors allowed ONLY inside multi-word names (e.g. "Abdul bin Aziz").
_NAME_CONNECTORS = frozenset({"bin", "ibn", "binte", "al", "ul", "el", "de", "da", "la", "van", "von"})

# Devanagari letters/matras/marks ONLY — explicitly excludes digits (0966-096F) and danda/double-danda (0964-0965).
_DEVA_CHAR = r"[\u0901-\u0963\u0970-\u097f]"
_LATIN_NAME_TOK = r"(?:[A-Z][a-zA-Z'’-]{1,24}\.?|[A-Z]\.)"
_DEVA_NAME_TOK = rf"{_DEVA_CHAR}{{2,24}}"
_NAME_SEQ = rf"(?:(?:{_LATIN_NAME_TOK}|{_DEVA_NAME_TOK})(?:\s+(?:{_LATIN_NAME_TOK}|{_DEVA_NAME_TOK})){{0,3}})"

# 1. Clinician patterns (`STAFF_OR_FACILITY`)
_CLINICIAN_RE = re.compile(
    rf"(?:(?<!\w)(?:[Dd]r\.?|डॉ\.?|डॉक्टर)\s+(?P<name>{_NAME_SEQ}))|"
    rf"(?:\b(?i:Consultant|Attending\s+(?:Doctor|Physician)|Referring\s+Doctor|Physician|Surgeon|Prescribed\s+by|Signed\s+by)\s*[:=-]?\s*"
    rf"(?P<name2>(?:(?:[Dd]r\.?|डॉ\.?)\s+)?{_NAME_SEQ}))",
    re.UNICODE,
)

# 2. Explicit Relative relations (`W/o`, `S/o`, `D/o`, guardian, Hindi kinship)
_RELATIVE_RE = re.compile(
    rf"(?:(?<!\w)(?i:W/o|S/o|D/o|Wife\s+of|Son\s+of|Daughter\s+of|Father\s+of|Mother\s+of|"
    rf"Guardian|Next\s+of\s+Kin|NOK)|पत्नी|पुत्र|पुत्री|पिता|माता|अभिभावक)\s*[:.,-]?\s*"
    rf"(?:(?:(?i:Mr|Mrs|Ms|Smt|Shri|Sri)|श्री|श्रीमती)\.?\s+)?(?P<rel>{_NAME_SEQ})",
    re.UNICODE,
)

# 3. Structural patient name preceding demographic/relation markers (works even WITHOUT "Patient:" label!)
#    Matches: "Meera, W/o Rajan", "Anil Kapoor, 52/M", "सुनीता देवी, 34 वर्ष", "Rohan Das, DOB:"
_PRE_DEMOGRAPHIC_PATIENT_RE = re.compile(
    rf"(?P<pt>{_NAME_SEQ})\s*,\s*"
    rf"(?:(?i:W/o|S/o|D/o|C/O|DOB|Phone|Mobile|Ph|UHID|MRN|ABHA)|"
    rf"पत्नी|पुत्र|पुत्री|उम्र|आयु|फोन|जन्म|"
    rf"\d{{1,3}}\s*(?:(?i:yrs?|years?|y)|वर्ष|साल)|"
    rf"\d{{1,3}}\s*/\s*(?i:M|F|Male|Female))\b",
    re.UNICODE,
)

# 4. C/O disambiguation pattern
_CARE_OF_RE = re.compile(
    r"(?<!\w)(?i:C/O|Care\s+of|केयर\s+ऑफ)\s*[:.-]?\s*(?P<rhs>[^,;\n.।॥]{2,50})",
    re.UNICODE,
)

# 5. Labeled patient name (`Patient:`, `Pt:`, `Name:`, `मरीज:`, `नाम:`)
_LABELED_PATIENT_RE = re.compile(
    rf"(?<!\w)(?:(?i:Patient(?:\s+Name)?|Pt(?:\s+Name)?|Name)|मरीज(?:\s+का\s+नाम)?|रोगी(?:\s+का\s+नाम)?|नाम)"
    rf"\s*[:=-]\s*(?:(?:(?i:Mr|Mrs|Ms|Miss|Smt|Shri|Sri)|श्री|श्रीमती|कुमारी)\.?\s+)?"
    rf"(?P<pt>{_NAME_SEQ})",
    re.UNICODE,
)

# 6. Honorific-anchored names (`Mr. Rahul Verma`, `Smt. Meera`, `Arif sahab`, `Arif ji`, `आरिफ जी`)
_PREFIX_HONORIFIC_RE = re.compile(
    rf"(?<!\w)(?:Mr|Mrs|Ms|Miss|Smt|Shri|Sri|Shree|Kumari|श्री|श्रीमती|कुमारी)\.?\s+(?P<name>{_NAME_SEQ})",
    re.UNICODE,
)
_SUFFIX_HONORIFIC_RE = re.compile(
    rf"(?P<name>(?:{_LATIN_NAME_TOK}|{_DEVA_NAME_TOK})"
    rf"(?:\s+(?:{_LATIN_NAME_TOK}|{_DEVA_NAME_TOK}))?)\s+"
    rf"(?:(?i:ji|sahab|sahib|saheb)|जी|साहब|साहिब)(?!\w)",
    re.UNICODE,
)

# 7. Free-text Age (captures ONLY integer digits for M3 AdaptiveGeneralizer)
_AGE_RE = re.compile(
    r"(?:(?<!\w)(?:(?i:Age)|उम्र|आयु)\s*[:=-]?\s*(?P<age1>\d{1,3})\s*(?:(?i:yrs?|years?|y)|वर्ष|साल)?\b|"
    r"\b(?P<age2>\d{1,3})\s*(?i:yrs?|years?)\s*(?i:old|/M|/F|Male|Female)?\b|"
    r"\b(?P<age3>\d{1,3})\s*/\s*(?i:M|F|Male|Female)\b)",
    re.UNICODE,
)

# 8. Labeled AND structural unprefixed Indian addresses + Village/District markers
_ADDRESS_LABELED_RE = re.compile(
    r"(?:(?<!\w)(?:(?i:Address|Add|R/o|Resident\s+of)|पता|निवासी)\s*[:=-]?\s*(?P<addr>[^\n;।॥]{5,90})|"
    r"\b(?:(?i:H\.?\s*No\.?|House\s*No\.?|Plot\s*No\.?|Flat\s*(?:No\.?)?)|मकान\s*नं\.?)\s*[:#.-]?\s*[^\n;।॥]{3,80})",
    re.UNICODE,
)
_ADDRESS_UNLABELED_RE = re.compile(
    r"\b(?:\d{1,4}[A-Za-z]?(?:/\d{1,3})?,\s*)?"
    r"[A-Za-z0-9\u0901-\u0963\s.-]{2,30}\s+"
    r"(?:Nagar|Colony|Vihar|Enclave|Puram|Marg|Road|Street|Lane|Gali|Mohalla|Sector|Phase|Block|"
    r"नगर|कॉलोनी|विहार|मार्ग|गली|मोहल्ला)\b"
    r"(?:\s*\d{0,3}[A-Za-z]?,\s*[A-Za-z\u0901-\u0963\s-]{2,25}(?:\s*[-,]?\s*[1-8]\d{5})?)?",
    re.IGNORECASE | re.UNICODE,
)
_VILLAGE_RE = re.compile(
    rf"(?<!\w)(?:(?i:Village|Vill|Gram|Dist|District|Tehsil|Taluka)|ग्राम|गांव|जिला|तहसील)\s*[:.-]?\s*"
    rf"(?P<geo>(?:[A-Za-z]|{_DEVA_CHAR})(?:[A-Za-z\s-]|{_DEVA_CHAR}){{1,30}})",
    re.UNICODE,
)


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    """Intermediate context-detected span in original UTF-8 coordinates."""

    start: int
    end: int
    category: str
    role: SpanRole
    confidence: float
    detector_source: str
    attr_key: str | None = None
    attr_val: str | None = None
    extra_attr_key: str | None = None
    extra_attr_val: str | None = None


def _trim_name_fragment(fragment: str) -> str:
    """Stop a greedy name match using grammatical, casing, and field-label boundaries."""
    tokens = fragment.strip().split()
    kept: list[str] = []
    for idx, tok in enumerate(tokens):
        raw_tok = tok.strip(",;:-()[]{}।॥")
        low = raw_tok.rstrip(".").lower()
        if not raw_tok or any(ch.isdigit() for ch in raw_tok):
            break
        if raw_tok in _DEVA_GRAMMAR_BOUNDARIES or low in _LATIN_NON_NAME_WORDS:
            break
        if low in {"s/o", "w/o", "d/o", "c/o", "h/o"}:
            break
        # Reject lowercase Latin tokens unless short interior connector like 'bin'/'al'.
        if raw_tok.isascii() and raw_tok[0].islower():
            if not (idx > 0 and low in _NAME_CONNECTORS):
                break
        kept.append(raw_tok)
    while kept and kept[-1].lower() in _NAME_CONNECTORS:
        kept.pop()
    if kept and kept[-1].endswith(".") and len(kept[-1]) > 2:
        kept[-1] = kept[-1].rstrip(".")
    return " ".join(kept)


def detect_context_candidates(
    raw_text: str,
    *,
    indexed: IndexedText | None = None,
) -> list[ContextCandidate]:
    """Extract multilingual role-disambiguated spans from free-text clinical notes."""
    if not raw_text or not raw_text.strip():
        return []

    idx_text = indexed or normalize_with_offset_map(raw_text)
    norm = idx_text.normalized
    candidates: list[ContextCandidate] = []

    def add_name_match(
        norm_start: int,
        norm_end: int,
        category: str,
        role: SpanRole,
        confidence: float,
        source: str,
        *,
        include_prefix_start: int | None = None,
        emit_patient_attrs: bool = False,
        emit_relative_attrs: bool = False,
    ) -> None:
        raw_frag = norm[norm_start:norm_end]
        trimmed = _trim_name_fragment(raw_frag)
        if not trimmed:
            return
        sub_idx = raw_frag.find(trimmed)
        if sub_idx == -1:
            return
        adj_start = norm_start + sub_idx
        adj_end = adj_start + len(trimmed)

        norm_name = normalize_person_name(trimmed)
        if not norm_name.canonical_name:
            return

        span_start = include_prefix_start if include_prefix_start is not None else adj_start
        s, e = idx_text.to_original_span(span_start, adj_end)

        attr_key = attr_val = extra_key = extra_val = None
        if emit_patient_attrs:
            attr_key, attr_val = "names", norm_name.canonical_name
            if norm_name.name_key:
                extra_key, extra_val = "name_keys", norm_name.name_key
        elif emit_relative_attrs and norm_name.name_key:
            attr_key, attr_val = "relative_name_keys", norm_name.name_key

        candidates.append(
            ContextCandidate(
                start=s,
                end=e,
                category=category,
                role=role,
                confidence=confidence,
                detector_source=source,
                attr_key=attr_key,
                attr_val=attr_val,
                extra_attr_key=extra_key,
                extra_attr_val=extra_val,
            )
        )

    # 1. Clinicians (`Dr. Ramesh`, `डॉ. शर्मा`) -> STAFF_OR_FACILITY
    for m in _CLINICIAN_RE.finditer(norm):
        grp = "name" if m.group("name") else "name2"
        ns, ne = m.span(grp)
        prefix_start = m.start() if grp == "name" else ns
        add_name_match(
            ns, ne, "CLINICIAN_NAME", SpanRole.STAFF_OR_FACILITY, 0.96, "context_clinician",
            include_prefix_start=prefix_start,
        )

    # 2. Relatives (`W/o`, `S/o`, `D/o`, `पत्नी`, `पुत्र`, `पुत्री`) -> RELATIVE_NAME
    for m in _RELATIVE_RE.finditer(norm):
        ns, ne = m.span("rel")
        add_name_match(
            ns, ne, "RELATIVE_NAME", SpanRole.DIRECT_PII, 0.96, "context_relative",
            emit_relative_attrs=True,
        )

    # 3. `C/O` disambiguation (Care-of relative vs Complaint-of clinical symptom)
    for m in _CARE_OF_RE.finditer(norm):
        rhs = m.group("rhs").strip()
        left_ctx = norm[max(0, m.start() - 40) : m.start()]
        if is_clinical_complaint_phrase(rhs, left_ctx):
            continue
        rhs_start = m.start("rhs")
        name_m = re.match(
            rf"(?:(?:(?i:Mr|Mrs|Ms|Smt|Shri)|श्री)\.?\s+)?({_NAME_SEQ})",
            rhs,
            re.UNICODE,
        )
        if name_m:
            add_name_match(
                rhs_start + name_m.start(1),
                rhs_start + name_m.end(1),
                "RELATIVE_NAME",
                SpanRole.DIRECT_PII,
                0.90,
                "context_care_of_relative",
                emit_relative_attrs=True,
            )

    # 4. Structural patient name preceding demographics/kinship (`Anil Kapoor, 52/M`, `Meera, W/o Rajan`)
    for m in _PRE_DEMOGRAPHIC_PATIENT_RE.finditer(norm):
        ns, ne = m.span("pt")
        add_name_match(
            ns, ne, "PATIENT_NAME", SpanRole.DIRECT_PII, 0.94, "context_pre_demographic_patient",
            emit_patient_attrs=True,
        )

    # 5. Labeled patient name (`Patient: Mohd. Arif`, `मरीज: मोहम्मद आरिफ`)
    for m in _LABELED_PATIENT_RE.finditer(norm):
        ns, ne = m.span("pt")
        add_name_match(
            ns, ne, "PATIENT_NAME", SpanRole.DIRECT_PII, 0.96, "context_labeled_patient",
            emit_patient_attrs=True,
        )

    # 6. Honorific-anchored names (`Mr. Rahul`, `Arif sahab`, `Arif ji`, `आरिफ जी`)
    for m in _PREFIX_HONORIFIC_RE.finditer(norm):
        ns, ne = m.span("name")
        add_name_match(
            ns, ne, "PERSON_NAME", SpanRole.DIRECT_PII, 0.88, "context_prefix_honorific",
            emit_patient_attrs=True,
        )

    for m in _SUFFIX_HONORIFIC_RE.finditer(norm):
        ns, ne = m.span("name")
        raw_frag = norm[ns:ne]
        trimmed = _trim_name_fragment(raw_frag)
        if trimmed and normalize_person_name(trimmed).canonical_name:
            sub_idx = raw_frag.find(trimmed)
            if sub_idx == -1:
                continue
            adj_s = ns + sub_idx
            s, e = idx_text.to_original_span(adj_s, m.end())
            norm_n = normalize_person_name(trimmed)
            candidates.append(
                ContextCandidate(
                    start=s,
                    end=e,
                    category="PERSON_NAME",
                    role=SpanRole.DIRECT_PII,
                    confidence=0.89,
                    detector_source="context_suffix_honorific",
                    attr_key="names",
                    attr_val=norm_n.canonical_name,
                    extra_attr_key="name_keys" if norm_n.name_key else None,
                    extra_attr_val=norm_n.name_key or None,
                )
            )

    # 7. Free-text Age (exact integer digits only for M3 AdaptiveGeneralizer)
    for m in _AGE_RE.finditer(norm):
        for grp in ("age1", "age2", "age3"):
            if m.group(grp) is not None:
                age_val = int(m.group(grp))
                if 0 <= age_val <= 125:
                    s, e = idx_text.to_original_span(*m.span(grp))
                    if idx_text.original[s:e].isascii() and idx_text.original[s:e].isdigit():
                        candidates.append(
                            ContextCandidate(
                                start=s,
                                end=e,
                                category="AGE",
                                role=SpanRole.QUASI_IDENTIFIER,
                                confidence=0.93,
                                detector_source="context_age",
                                attr_key="ages",
                                attr_val=str(age_val),
                            )
                        )
                break

    # 8. Labeled & structural unprefixed Indian Addresses + Villages
    for m in _ADDRESS_LABELED_RE.finditer(norm):
        ns, ne = m.span("addr") if m.group("addr") is not None else m.span(0)
        frag = norm[ns:ne]
        stop_m = re.search(
            r"(?:\.\s+(?=[A-Z\u0900-\u097f])|\b(?:Phone|Mobile|Tel|Email|UHID|MRN|ABHA|Aadhaar|BP|HR|SpO2|Temp|Dr\.|डॉ\.|C/O\s+fever)\b)",
            frag,
            re.I,
        )
        if stop_m and stop_m.start() >= 5:
            ne = ns + stop_m.start()
        while ne > ns and norm[ne - 1] in " ,;:-।॥.":
            ne -= 1
        if ne > ns:
            s, e = idx_text.to_original_span(ns, ne)
            candidates.append(
                ContextCandidate(
                    start=s,
                    end=e,
                    category="ADDRESS",
                    role=SpanRole.DIRECT_PII,
                    confidence=0.90,
                    detector_source="context_address",
                )
            )

    for m in _ADDRESS_UNLABELED_RE.finditer(norm):
        ns, ne = m.span(0)
        while ns < ne and norm[ns] in " ,;:-":
            ns += 1
        while ne > ns and norm[ne - 1] in " ,;:-।॥.":
            ne -= 1
        if ne - ns >= 6:
            s, e = idx_text.to_original_span(ns, ne)
            candidates.append(
                ContextCandidate(
                    start=s,
                    end=e,
                    category="ADDRESS",
                    role=SpanRole.DIRECT_PII,
                    confidence=0.84,
                    detector_source="context_address_structural",
                )
            )

    for m in _VILLAGE_RE.finditer(norm):
        ns, ne = m.span("geo")
        frag = _trim_name_fragment(norm[ns:ne])
        if not frag:
            continue
        sub_idx = norm[ns:ne].find(frag)
        adj_s = ns + sub_idx
        adj_e = adj_s + len(frag)
        s, e = idx_text.to_original_span(adj_s, adj_e)
        is_dist = bool(re.search(r"(?:Dist|District|जिला)", m.group(0), re.I))
        candidates.append(
            ContextCandidate(
                start=s,
                end=e,
                category="LOCATION" if is_dist else "VILLAGE",
                role=SpanRole.QUASI_IDENTIFIER,
                confidence=0.90,
                detector_source="context_geo",
                attr_key="geo_keys",
                attr_val=frag.lower(),
                extra_attr_key="districts" if is_dist else None,
                extra_attr_val=frag if is_dist else None,
            )
        )

    return candidates
