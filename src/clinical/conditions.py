# Purpose: Morphological, eponymous, structural C/O complaint, and procedure detection without closed word lists.
"""Diagnosis, symptom, eponym, and procedure detection using medical morphology and syntax."""

from __future__ import annotations

import re

from src.detection.normalization import IndexedText, normalize_with_offset_map

from .medications import ClinicalMatch

# Morphological Greek/Latin medical suffixes covering thousands of unseen diagnoses & procedures.
_DIAGNOSIS_MORPH_SUFFIXES = (
    r"itis|osis|emia|aemia|uria|algia|pathy|megaly|penia|rrhea|rrhoea|"
    r"pnea|pnoea|edema|oedema|spasm|plasia|iasis|stenosis|sclerosis|"
    r"carcinoma|sarcoma|lymphoma|leukemia|leukaemia|aneurysm|thrombosis|"
    r"embolism|ischemia|ischaemia|infarction|necrosis|fibrosis|cirrhosis|"
    r"insufficiency|deficiency|ism"
)
_PROCEDURE_MORPH_SUFFIXES = (
    r"ectomy|otomy|ostomy|plasty|scopy|graphy|gram|tripsy|desis|centesis|"
    r"lysis|therapy|transfusion|biopsy|catheterization|implantation|resection|"
    r"debridement|dialysis|ventilation|intubation|nebulization|dilation"
)

# Open-ended eponymous condition/procedure pattern (protects "Parkinson's disease", "Takayasu arteritis", "Apgar score", etc.)
_EPONYM_RE = re.compile(
    r"(?<!\w)(?:Non-)?[A-Z][a-zA-Z'’-]{2,24}(?:'s|s)?\s+"
    r"(?:disease|syndrome|palsy|phenomenon|lymphoma|thyroiditis|arteritis|triad|"
    r"sign|reflex|fracture|score|scale|classification|lesion|tumor|tumour)\b",
    re.UNICODE,
)

# Morphological diagnosis/procedure words (optional 1-word anatomical/type qualifier like "Acute", "Chronic", "Type 2").
_QUALIFIER = r"(?:(?:Acute|Chronic|Severe|Mild|Moderate|Bilateral|Unilateral|Primary|Secondary|Type\s*[12]|Pulmonary|Renal|Hepatic|Coronary|Cerebral|Peripheral|Congestive|Bronchial|Enteric|Urinary\s+Tract|Diabetes)\s+)"
_DIAGNOSIS_MORPH_RE = re.compile(
    rf"(?<!\w)(?:{_QUALIFIER})?[A-Za-z][a-zA-Z-]{{2,28}}(?:{_DIAGNOSIS_MORPH_SUFFIXES})\b",
    re.IGNORECASE,
)
_PROCEDURE_MORPH_RE = re.compile(
    rf"(?<!\w)(?:{_QUALIFIER})?[A-Za-z][a-zA-Z-]{{2,28}}(?:{_PROCEDURE_MORPH_SUFFIXES})\b",
    re.IGNORECASE,
)

# Compact core abbreviations & non-suffixed terms (English + Hindi) that lack standard Greek/Latin suffixes.
_CORE_CLINICAL_TERMS: tuple[str, ...] = (
    "fever", "pyrexia", "cough", "cold", "pain", "ache", "headache", "breathlessness",
    "sob", "vomiting", "nausea", "loose motion", "loose motions", "weakness", "fatigue",
    "dizziness", "giddiness", "vertigo", "syncope", "palpitations", "swelling", "rash",
    "itching", "jaundice", "bleeding", "seizure", "convulsion", "chills", "rigors",
    "constipation", "insomnia", "hypertension", "htn", "diabetes mellitus", "t2dm", "t1dm",
    "copd", "asthma", "cad", "ckd", "aki", "uti", "mi", "stemi", "nstemi", "cva",
    "stroke", "dengue", "malaria", "typhoid", "sepsis", "covid-19", "cabg", "ptca",
    "pci", "lscs", "ecg", "mri", "ct scan", "x-ray", "usg", "ultrasound",
    # Hinglish & Hindi core symptom/condition words
    "bukhar", "bukhaar", "khansi", "khaansi", "dard", "kamzori", "chakkar", "ulti",
    "dast", "sujan", "khujli", "ghabrahat", "bechaini", "saans",
    "बुखार", "ज्वर", "खांसी", "जुकाम", "दर्द", "कमजोरी", "चक्कर", "उल्टी", "दस्त",
    "सूजन", "खुजली", "घबराहट", "थकान", "मधुमेह", "उच्च रक्तचाप", "दमा", "पीलिया",
    "सर्जरी", "ऑपरेशन",
)
_CORE_CLINICAL_ALT = "|".join(re.escape(t) for t in sorted(_CORE_CLINICAL_TERMS, key=len, reverse=True))

_DURATION_TAIL = r"(?:\s+(?:x|for|since)\s+\d+\s*(?:d|day|days|hr|hrs|hours?|wk|wks|weeks?|mo|months?)|\s+since\s+(?:yesterday|morning|evening|night))?"

_CLINICAL_DESCRIPTOR_RE = re.compile(
    rf"(?:{_DIAGNOSIS_MORPH_SUFFIXES}|{_PROCEDURE_MORPH_SUFFIXES})\b|"
    rf"\b(?:mild|moderate|severe|acute|chronic|intermittent|high[\s-]?grade|low[\s-]?grade|"
    rf"radiating|persistent|bilateral|left|right|central|epigastric|chest|abdominal|"
    rf"pedal|suprapubic|loose|dry|productive|difficulty|shortness|loss\s+of|burning|"
    rf"x\s*\d+\s*(?:d|day|days|hr|hrs|wk|wks|mo)|for\s+\d+\s*(?:d|day|days|wk|mo)|since\s+\w+)\b|"
    rf"(?<!\w)(?:{_CORE_CLINICAL_ALT})(?!\w)",
    re.IGNORECASE | re.UNICODE,
)

# Explicit clinical complaint/history cue: "C/O <clinical phrase>", "H/o <condition>", "K/C/O <condition>".
_COMPLAINT_OR_HISTORY_RE = re.compile(
    rf"(?<!\w)(?P<prefix>C/O|c/o|Complaint\s+of|H/O|H/o|h/o|History\s+of|K/C/O|k/c/o)\s+"
    rf"(?P<rhs>[^,;\n.।॥]{{2,55}})",
    re.IGNORECASE | re.UNICODE,
)

_CORE_TERM_RE = re.compile(rf"(?<!\w)(?:{_QUALIFIER})?(?:{_CORE_CLINICAL_ALT})(?!\w){_DURATION_TAIL}", re.IGNORECASE | re.UNICODE)

# Non-clinical proper-name cues inside C/O (titles, kinship, address markers) -> care-of relative, not complaint.
_CARE_OF_PERSON_CUE_RE = re.compile(
    r"(?:^(?:Mr|Mrs|Ms|Miss|Smt|Shri|Sri|Dr|श्री|श्रीमती|डॉ)\.?\s|"
    r"\b(?:ji|sahab|sahib|saheb|S/o|W/o|D/o|H\.?\s*No|Sector|Road|Nagar|Colony)\b|"
    r"(?:जी|साहब|मकान|नगर|ग्राम)\b)",
    re.IGNORECASE | re.UNICODE,
)

# English person-name shape: 1-3 Proper-Cased words (e.g. "Ramesh", "Ramesh Kumar") with NO lowercase/clinical markers.
_PROPER_NAME_ONLY_RE = re.compile(
    r"^(?:[A-Z][a-z'’-]{1,24}|[A-Z]\.)(?:\s+(?:[A-Z][a-z'’-]{1,24}|[A-Z]\.)){0,3}$"
)


def is_clinical_complaint_phrase(rhs: str, left_context: str = "") -> bool:
    """Disambiguate `C/O <rhs>` structurally without relying on an exhaustive symptom list.

    Returns True when `<rhs>` is a clinical complaint/history rather than a relative's name.
    """
    cleaned = rhs.strip(" ,;:.।॥")
    if not cleaned:
        return False

    # 1. Explicit person/address cues on RHS -> Care-of (not complaint).
    if _CARE_OF_PERSON_CUE_RE.search(cleaned):
        return False

    # 2. Clinical morphology, clinical core terms, severity/duration modifiers, or medical suffixes -> Complaint.
    if _CLINICAL_DESCRIPTOR_RE.search(cleaned) or _EPONYM_RE.search(cleaned):
        return True

    # 3. Structural case signal in English/Latin: lowercase multi-word or lowercase single noun after C/O
    #    (e.g. "C/O loose stools", "C/O hematuria") is clinical, whereas Proper-Cased tokens are likely names
    #    unless left context explicitly marks a clinical complaint section.
    if any(ch.isascii() and ch.isalpha() for ch in cleaned):
        if _PROPER_NAME_ONLY_RE.match(cleaned):
            # Proper-cased phrase like "C/O Suresh" -> care-of unless preceded by clinical verb/section.
            if re.search(r"(?:presented\s+with|chief\s+complaints?|complaints?|admitted\s+with|h/o)\s*[:,-]?\s*$", left_context, re.I):
                return True
            return False
        # Lowercase Latin phrase (e.g., "C/O dry cough", "C/O epigastric burning") -> clinical complaint.
        if cleaned[0].islower():
            return True

    return False


def detect_condition_and_procedure_spans(
    raw_text: str,
    indexed: IndexedText | None = None,
) -> list[ClinicalMatch]:
    """Detect diagnoses, eponyms, C/O & H/o clinical complaints, and procedures."""
    if not raw_text or not raw_text.strip():
        return []

    idx_text = indexed or normalize_with_offset_map(raw_text)
    norm = idx_text.normalized
    matches: list[ClinicalMatch] = []

    # 1. Open-ended medical eponyms ("Parkinson's disease", "Takayasu arteritis", "Apgar score").
    for m in _EPONYM_RE.finditer(norm):
        s, e = idx_text.to_original_span(m.start(), m.end())
        if s < e:
            matches.append(ClinicalMatch(start=s, end=e, category="DIAGNOSIS", confidence=0.98))

    # 2. Morphological diagnoses & procedures.
    for m in _DIAGNOSIS_MORPH_RE.finditer(norm):
        s, e = idx_text.to_original_span(m.start(), m.end())
        if s < e:
            matches.append(ClinicalMatch(start=s, end=e, category="DIAGNOSIS", confidence=0.93))

    for m in _PROCEDURE_MORPH_RE.finditer(norm):
        s, e = idx_text.to_original_span(m.start(), m.end())
        if s < e:
            matches.append(ClinicalMatch(start=s, end=e, category="PROCEDURE", confidence=0.94))

    # 3. Context-verified C/O complaint-of & H/o history-of phrases.
    for m in _COMPLAINT_OR_HISTORY_RE.finditer(norm):
        prefix = m.group("prefix").lower()
        rhs = m.group("rhs")
        left_ctx = norm[max(0, m.start() - 40) : m.start()]
        is_history = prefix.startswith(("h/", "history", "k/c/o"))
        if is_history or is_clinical_complaint_phrase(rhs, left_ctx):
            # Trim trailing conjunctions/next clauses if needed (stop before "and Dr." / ", Phone").
            end_pos = m.end()
            stop_m = re.search(r"\b(?:Phone|Mobile|UHID|MRN|ABHA|Dr\.|डॉ\.)\b", rhs, re.I)
            if stop_m:
                end_pos = m.start("rhs") + stop_m.start()
            while end_pos > m.start() and norm[end_pos - 1] in " ,;:-।॥":
                end_pos -= 1
            s, e = idx_text.to_original_span(m.start(), end_pos)
            if s < e:
                matches.append(ClinicalMatch(start=s, end=e, category="CLINICAL", confidence=0.96))

    # 4. Core clinical terms (English / Hindi / Hinglish).
    for m in _CORE_TERM_RE.finditer(norm):
        s, e = idx_text.to_original_span(m.start(), m.end())
        if s < e:
            matches.append(ClinicalMatch(start=s, end=e, category="CLINICAL", confidence=0.90))

    return matches
