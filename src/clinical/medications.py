# Purpose: Structural, INN-stem, unit-anchored, and form-based medication/dosage detection.
"""General medication, dosage, and administration schedule detection."""

from __future__ import annotations

from dataclasses import dataclass
import re

from src.detection.normalization import IndexedText, normalize_with_offset_map

# Core short drug names lacking standard WHO INN stems (kept compact; INN stems + grammar cover unseen drugs).
_CORE_NON_STEM_DRUGS: tuple[str, ...] = (
    "paracetamol", "acetaminophen", "dolo", "crocin", "calpol", "aspirin",
    "ecosprin", "insulin", "warfarin", "heparin", "digoxin", "atropine",
    "adrenaline", "noradrenaline", "dopamine", "dobutamine", "lasix",
    "augmentin", "combiflam", "shelcal", "pan-d", "thyronorm", "montair",
    "avil", "metronidazole", "albendazole", "ivermectin", "nitroglycerin",
)

# WHO INN pharmacological stems (matches thousands of unseen generic medications automatically).
_INN_STEM_REGEX = (
    r"(?:cef|ceph)[a-z]{3,}|"
    r"[a-z]{3,}(?:"
    r"cillin|mycin|cycline|floxacin|azole|prazole|statin|sartan|pril|olol|"
    r"dipine|formin|gliptin|gliflozin|navir|conazole|triptan|parin|xaban|"
    r"tidine|setron|zepam|zolam|caine|phylline|lukast|asone|olone|fenac|"
    r"profen|barbital|lukast|oprazole|glitazone|mustine|platin|rubicin|"
    r"taxel|tecan|zomib|ciclib|parib|mab|nib|vir"
    r")"
)

_FORM_PREFIX = (
    r"(?:Tab(?:let)?s?|Cap(?:sule)?s?|Inj(?:ection)?|Syp|Syrup|Susp(?:ension)?|"
    r"Drops?|Oint(?:ment)?|Gel|Cream|Neb(?:ulization)?|Inh(?:aler)?|Respules?|"
    r"Sachet|Patch|Lotion|Spray|Infusion|IVF|टेबलेट|टैबलेट|गोली|कैप्सूल|सिरप|इंजेक्शन)"
)
_UNIT = r"(?:mg|mcg|ug|µg|g|gm|ml|mL|L|IU|units?|%|mmol|mEq|drops?|puffs?)"
_ROUTE = r"(?:PO|IV|IM|SC|SL|PR)"
_FREQ = r"(?:OD|BD|BID|TDS|TID|QID|HS|SOS|PRN|STAT|Q\d+H)"
_ROUTE_FREQ = rf"(?:(?:\s+(?:{_ROUTE}|{_FREQ})){{1,2}})"
_DURATION = r"(?:(?:x|for)\s*\d+\s*(?:d|day|days|hr|hrs|hours?|wk|wks|weeks?|mo|months?))"
_SCHEDULE = r"(?:[0-2](?:/2)?-[0-2](?:/2)?-[0-2](?:/2)?(?:-[0-2])?)"

_CORE_DRUG_ALT = "|".join(re.escape(d) for d in _CORE_NON_STEM_DRUGS)
_NON_DRUG_STOP = r"(?:patient|pt|mr|mrs|ms|dr|name|for|with|and|to|मरीज|रोगी|डॉ|को|के|का|की)"

# 1. Explicit dosage-form prefix + arbitrary unseen drug name(s) + optional strength/route/freq/duration.
_STRUCTURAL_FORM_MED_RE = re.compile(
    rf"\b{_FORM_PREFIX}\.?\s+"
    rf"(?!{_NON_DRUG_STOP}\b)"
    rf"[A-Za-z\u0901-\u0963][A-Za-z0-9\u0901-\u0963-]{{1,28}}"
    rf"(?:\s+(?!{_NON_DRUG_STOP}\b)(?:[A-Za-z0-9-]{{1,18}})){{0,2}}"
    rf"(?:\s+\d+(?:\.\d+)?(?:\s*{_UNIT})?)?"
    rf"(?:{_ROUTE_FREQ})?(?:\s+{_SCHEDULE})?(?:\s+{_DURATION})?",
    re.IGNORECASE | re.UNICODE,
)

# 2. INN-stem or core drug token + optional strength/route/freq/duration.
_INN_OR_CORE_MED_RE = re.compile(
    rf"\b(?:{_INN_STEM_REGEX}|{_CORE_DRUG_ALT})\b"
    rf"(?:\s+\d+(?:\.\d+)?(?:\s*{_UNIT})?)?"
    rf"(?:{_ROUTE_FREQ})?(?:\s+{_SCHEDULE})?(?:\s+{_DURATION})?",
    re.IGNORECASE,
)

# 3. Any unseen brand/word followed immediately by numeric strength + explicit clinical unit.
_UNIT_ANCHORED_MED_RE = re.compile(
    rf"\b(?!(?:age|wt|ht|temp|bp|pr|hr|rr|spo2|id|uhid|mrn|abha|pin|room|ward|bed|day|days|wk|mo)\b)"
    rf"[A-Za-z][A-Za-z0-9-]{{2,24}}\s+\d+(?:\.\d+)?\s*{_UNIT}\b"
    rf"(?:{_ROUTE_FREQ})?(?:\s+{_SCHEDULE})?(?:\s+{_DURATION})?",
    re.IGNORECASE,
)

# 4. Standalone dosing frequency schedules ("1-0-1", "1/2-0-1/2", "BD x 5 days").
_SCHEDULE_RE = re.compile(
    rf"(?<!\d){_SCHEDULE}(?!\d)|"
    rf"\b{_FREQ}\s+{_DURATION}\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ClinicalMatch:
    """Matched clinical span in original UTF-8 coordinates."""

    start: int
    end: int
    category: str
    confidence: float


def detect_medication_spans(
    raw_text: str,
    indexed: IndexedText | None = None,
) -> list[ClinicalMatch]:
    """Detect medications, dosages, and frequency schedules with exact original bounds."""
    if not raw_text or not raw_text.strip():
        return []

    idx_text = indexed or normalize_with_offset_map(raw_text)
    norm = idx_text.normalized
    matches: list[ClinicalMatch] = []

    patterns: tuple[tuple[re.Pattern[str], str, float], ...] = (
        (_STRUCTURAL_FORM_MED_RE, "MEDICATION", 0.96),
        (_INN_OR_CORE_MED_RE, "MEDICATION", 0.94),
        (_UNIT_ANCHORED_MED_RE, "DOSAGE", 0.91),
        (_SCHEDULE_RE, "FREQUENCY", 0.92),
    )

    for pattern, category, confidence in patterns:
        for m in pattern.finditer(norm):
            s, e = idx_text.to_original_span(m.start(), m.end())
            if s < e:
                matches.append(ClinicalMatch(start=s, end=e, category=category, confidence=confidence))

    return matches
