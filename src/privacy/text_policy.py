"""Entity-, email-, OCR-, date-, and age-aware policy for mixed text records."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import hmac
import re
import unicodedata

from src.contracts import PatientRecord, PrivacyDecision, TransformType
from src.detection.normalization import phonetic_token_key, transliterate_devanagari
from src.privacy.generalization import age_band


_LATIN = r"(?:[A-Z][A-Za-z'’.-]{1,30}|[A-Z]\.)"
_DEVA = r"[\u0901-\u0963\u0970-\u097f]{2,30}"
_ARABIC = r"[\u0600-\u06ff]{2,30}"
_NAME_TOKEN = rf"(?:{_LATIN}|{_DEVA}|{_ARABIC})"
_NAME = rf"{_NAME_TOKEN}(?:[ \t]+{_NAME_TOKEN}){{0,3}}"

# Boundary helpers that work reliably for Devanagari/Urdu combining marks (matras)
# where Python's `\b` fails because combining marks are non-`\w`.
_LBOUND = r"(?<![\w\u0900-\u097f\u0600-\u06ff])"
_RBOUND = r"(?![\w\u0900-\u097f\u0600-\u06ff])"

_DOCTOR_RE = re.compile(
    rf"(?i:(?:{_LBOUND}(?:Dr\.?|Doctor)|डॉ\.?|डॉक्टर|ڈاکٹر)){_RBOUND}?[ \t]+(?P<name>{_NAME})",
    re.UNICODE,
)

_COMMON_NAME_WORDS = frozenset({
    "prasad", "prem", "asha", "shanti", "bhagwati", "kamal", "daya",
    "sukh", "ganga", "lakshmi", "jyoti", "pooja", "deepak", "kiran",
    "mandir", "masjid", "jagran", "puja", "hope", "peace", "river",
})

_NON_PERSON_PHRASES = frozenset({
    "unknown", "unknown male", "unknown female", "unidentified", "na", "n/a",
    "none", "nil", "self", "patient", "deceased", "late", "mrd", "ymc",
    "gumshudgi", "report", "belt", "kotwali", "rpf", "ps", "platform",
    "station", "master", "aadhaar", "ppo", "citizen", "card", "kv",
    "class", "school", "college", "group", "parivar", "facebook",
    "whatsapp", "telegram", "station master", "station master sahab",
    "dob", "bd", "od", "tds", "qid", "pr", "bp", "hr", "rr", "id",
    "फोन", "उम्र", "आयु",
})

_NON_STAFF_SR_ROLES = frozenset({
    "engineer", "manager", "citizen", "executive", "officer", "clerk",
    "supervisor", "analyst", "developer", "director", "partner", "associate",
    "consultant", "advisor", "advocate", "accountant", "architect", "designer",
    "specialist", "technician", "coordinator", "inspector", "superintendent",
    "card",
})

_RELATION_WORDS = frozenset({
    "son", "daughter", "wife", "husband", "father", "mother", "guardian",
    "informant", "relative", "attendant", "bahu", "pota", "poti", "beta",
    "beti", "bhai", "behen", "neighbour", "neighbor", "donor",
    "पुत्र", "पुत्री", "पत्नी", "पोता", "पोते", "पोती", "बेटा", "बेटी", "बहू", "अभिभावक",
    "بیٹا", "بیٹی", "بیوی", "شوہر", "والد", "والدہ",
})

_RELATION_CUES = (
    r"s/o|w/o|d/o|b/o|son|daughter|wife|husband|father|mother|guardian|"
    r"informant|bahu|pota|poti|beta|beti|neighbou?r|donor|"
    r"पुत्र|पुत्री|पत्नी|पोता|पोते|पोती|बेटा|बेटी|बहू|अभिभावक|"
    r"بیٹا|بیٹی|بیوی|شوہر|والد|والدہ"
)

_STAFF_CUES = (
    r"HC|Ct\.?|SI|Sister|Sr\.|Nurse|ASHA[ \t]+(?:worker|karyakarta)|"
    r"ward[ \t]+boy|MRD[ \t]+typist|सामाजिक[ \t]+कार्यकर्ता|कार्यकर्ता|"
    r"verified[ \t]+by|exported[ \t]+by|typed[ \t]+by|checked[ \t]+by|"
    r"printed[ \t]+by(?![ \t:]*[A-Za-z0-9_.-]+\\)"
)

_URDU_MAP = {
    "ا": "a", "آ": "a", "أ": "a", "إ": "i", "ب": "b", "پ": "p", "ت": "t",
    "ٹ": "t", "ث": "s", "ج": "j", "چ": "ch", "ح": "h", "خ": "kh", "د": "d",
    "ڈ": "d", "ذ": "z", "ر": "r", "ڑ": "r", "ز": "z", "ژ": "zh", "س": "s",
    "ش": "sh", "ص": "s", "ض": "z", "ط": "t", "ظ": "z", "ع": "a", "غ": "gh",
    "ف": "f", "ق": "q", "ک": "k", "گ": "g", "ل": "l", "م": "m", "ن": "n",
    "ں": "n", "و": "o", "ہ": "h", "ھ": "h", "ی": "i", "ے": "e", "ئ": "i",
}

_LABEL_RE = re.compile(
    r"(?m)^(?P<prefix>[> \t]*)(?P<label>[^\n:=-]{2,40})[ \t]*(?P<sep>[:=-])[ \t]*(?P<value>[^\r\n]*)"
)
_EMAIL_HEADER_RE = re.compile(
    r"(?im)^(?P<prefix>[> \t]*)(?P<label>From|To|Cc|Bcc|Reply-To)[ \t]*:[ \t]*(?P<value>[^\r\n]+)"
)
_ATTACHMENT_LINE_RE = re.compile(
    r"(?im)^(?P<prefix>[> \t]*Attachments?[ \t]*:[ \t]*)(?P<value>[^\r\n]+)"
)
_WROTE_RE = re.compile(
    rf"(?im)^(?P<prefix>>?[ \t]*On[ \t]+[^\n,]+,[ \t]+)(?P<name>{_NAME})(?=[ \t]*<[^>]+>[ \t]+wrote:)"
)
_CHAT_RE = re.compile(
    rf"(?m)^(?:[> \t]*)\[[^\]\n]{{5,50}}\][ \t]*(?P<name>{_NAME})(?=[ \t]*:)"
)

_OCR_DIGITS = str.maketrans({
    "O": "0", "o": "0", "I": "1", "l": "1", "|": "1",
    "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2",
})


@dataclass(frozen=True, slots=True)
class Mention:
    start: int
    end: int
    role: str
    surface: str


def _canonical(value: str) -> str:
    return " ".join(re.findall(r"[\w\u0900-\u097f\u0600-\u06ff'’-]+", unicodedata.normalize("NFKC", value).casefold(), re.UNICODE))


def _is_non_person(surface: str) -> bool:
    canon = _canonical(surface)
    if not canon or canon in _NON_PERSON_PHRASES:
        return True
    words = canon.split()
    if all(w in _RELATION_WORDS or w in _NON_PERSON_PHRASES for w in words):
        return True
    if any(w in {"group", "parivar", "circle", "school", "college", "report", "belt", "card", "station", "master", "اسٹیشن", "ماسٹر"} for w in words):
        return True
    return False


def _token_phonetic(token: str) -> str:
    cleaned = token.strip(".'’\"-")
    if not cleaned:
        return ""
    if re.search(r"[\u0900-\u097f]", cleaned):
        latin = transliterate_devanagari(cleaned)
        return phonetic_token_key(latin)
    if re.search(r"[\u0600-\u06ff]", cleaned):
        latin = "".join(_URDU_MAP.get(ch, "") for ch in cleaned)
        return phonetic_token_key(latin)
    return phonetic_token_key(cleaned)


def _token_variants(token: str) -> set[str]:
    keys: set[str] = set()
    base = _token_phonetic(token)
    if base:
        keys.add(base)
    if token.isascii() and re.search(r"[l1]", token):
        alt = _token_phonetic(token.replace("1", "i").replace("l", "i"))
        if alt:
            keys.add(alt)
    return keys


def _doctor_spans(text: str) -> list[tuple[int, int]]:
    spans = [match.span() for match in _DOCTOR_RE.finditer(text)]
    surnames: set[str] = set()
    for match in _DOCTOR_RE.finditer(text):
        parts = _canonical(match.group("name")).split()
        if parts:
            surnames.add(parts[-1])
    if surnames:
        alt = "|".join(re.escape(s) for s in sorted(surnames, key=len, reverse=True))
        for match in re.finditer(rf"(?i){_LBOUND}(?:{alt})[ \t]+(?:madam|sir|ma'am){_RBOUND}", text):
            spans.append(match.span())
    return spans


def _inside(span: tuple[int, int], containers: list[tuple[int, int]]) -> bool:
    return any(span[0] < end and start < span[1] for start, end in containers)


def _label_role(label: str) -> str | None:
    if "(" in label and not re.search(r"(?i)\b(?:name|patient)\b", label):
        return None
    low = _canonical(label)
    words = set(low.split())
    if low in {"subject", "attachments", "attachment", "date", "doa", "dod", "history", "diagnosis", "treatment", "labs", "note"}:
        return None
    if words & {"doctor", "consultant", "physician", "surgeon"} or re.search(r"डॉक्टर|ڈاکٹر", label):
        return "doctor"
    if words & {"patient", "name", "beneficiary", "rogi", "mareez"} or re.search(r"मरीज|रोगी|نام|مریض", label):
        return "patient"
    if words & _RELATION_WORDS or re.search(r"पुत्र|पत्नी|पोता|बेटा|बहू|بیٹا|بیوی", label):
        return "relative"
    if words & {"police", "staff", "nurse", "sister", "asha", "mrd", "informant", "typed", "checked", "verified"} or re.search(r"कार्यकर्ता", label):
        return "staff" if "informant" not in words else "relative"
    return None


def _trim_relation_prefix(value: str, base: int) -> tuple[str, int]:
    match = re.match(rf"(?i)[ \t]*(?:(?:{_RELATION_CUES}){_RBOUND}[ \t:.-]*)+", value)
    if not match:
        return value, base
    return value[match.end():], base + match.end()


def _names_in_value(value: str, base: int, role: str) -> list[Mention]:
    found: list[Mention] = []
    # Split multi-entry label values (e.g. "Son Manoj Dubey, mob ... ; Bahu Priti ; Pota \"Chintu\"")
    for seg_match in re.finditer(r"[^;\n|]+", value):
        seg_text = seg_match.group(0)
        seg_base = base + seg_match.start()
        # Handle "Name, S/o Relative" inside a patient label line.
        if role == "patient":
            # Strip trailing parenthetical notes or other fields like ", DOB:" / ", फोन:"
            head_text = re.split(r"\s*\(|,\s*(?:DOB|Age|Sex|Phone|Mob|फोन|उम्र|आयु)\b", seg_text, maxsplit=1, flags=re.IGNORECASE)[0]
            if re.search(r"(?i)\b(?:unknown|unidentified)\b", head_text):
                # Still extract quoted nickname inside the parenthetical if present, but as "person", not "patient".
                continue
            rel_split = re.split(r"(?i),?[ \t]+(?:s/o|w/o|d/o|c/o)\b", head_text, maxsplit=1)
            if len(rel_split) == 2:
                pt_part = rel_split[0]
                pt_trimmed, pt_base = _trim_relation_prefix(pt_part, seg_base)
                for m in re.finditer(_NAME, pt_trimmed):
                    surface = m.group(0).strip()
                    if not _is_non_person(surface):
                        found.append(Mention(pt_base + m.start(), pt_base + m.end(), "patient", surface))
                rel_start = seg_base + len(head_text) - len(rel_split[1])
                rel_trimmed, rel_base = _trim_relation_prefix(rel_split[1], rel_start)
                for m in re.finditer(_NAME, rel_trimmed):
                    surface = m.group(0).strip()
                    if not _is_non_person(surface):
                        found.append(Mention(rel_base + m.start(), rel_base + m.end(), "relative", surface))
                continue

            pt_trimmed, pt_base = _trim_relation_prefix(head_text, seg_base)
            for m in re.finditer(_NAME, pt_trimmed):
                surface = m.group(0).strip()
                if not _is_non_person(surface):
                    found.append(Mention(pt_base + m.start(), pt_base + m.end(), "patient", surface))
            continue

        # Skip parenthetical school/class or belt/ID segments in Informant/Police lines.
        cleaned_seg = re.sub(r"\([^)]*(?:class|school|belt|kv)[^)]*\)", lambda m: " " * len(m.group(0)), seg_text, flags=re.IGNORECASE)
        for sub_match in re.finditer(r"[^,]+", cleaned_seg):
            sub_text = sub_match.group(0)
            sub_base = seg_base + sub_match.start()
            if re.search(r"(?i)\b(?:mob|phone|tel|pin|class|school|gumshudgi|report|belt|ps\b|platform|stall|aadhaar|ppo|sc/|auth-)\b", sub_text):
                # Still extract explicit police staff in Police lines (HC/Ct./SI <Name>)
                for pm in re.finditer(rf"(?i){_LBOUND}(?:RPF[ \t]+)?(?:HC|Ct\.?|SI){_RBOUND}[ \t]+(?P<name>{_NAME})", sub_text):
                    surface = pm.group("name").strip()
                    if not _is_non_person(surface):
                        found.append(Mention(sub_base + pm.start(), sub_base + pm.end("name"), "staff", sub_text[pm.start():pm.end("name")]))
                continue
            sub_trimmed, sub_base = _trim_relation_prefix(sub_text, sub_base)
            for m in re.finditer(_NAME, sub_trimmed):
                surface = m.group(0).strip()
                if _is_non_person(surface):
                    continue
                found.append(Mention(sub_base + m.start(), sub_base + m.end(), role, surface))
    return found


def _is_quoted_person_context(text: str, start: int, end: int, surface: str) -> bool:
    if _is_non_person(surface):
        return False
    low = _canonical(surface)
    words = low.split()
    before = text[max(0, start - 45):start]
    after = text[end:min(len(text), end + 30)]
    if re.search(r"(?i)(?:group|parivar|facebook|whatsapp|telegram|ख़ुद|خود کو)", before):
        return False
    if len(words) >= 2 and re.search(r"^[ \t'\"‘’]*\(\d{1,3}\b", after):
        return True
    if any(w in _COMMON_NAME_WORDS for w in words):
        return bool(
            re.search(r"(?i)(?:नाम|naam|called|alias|urf|aka|pota|पोते|पोता|बेटा|बताते|पुकारते)", before)
            or re.search(r"(?i)(?:बताते|पुकारते|आया|aaya|confirmed|ne\b)", after)
        )
    return bool(
        re.search(rf"(?i)(?:{_RELATION_CUES}|naam|नाम|alias|urf|aka|diya|बताते|पुकारते|कार्यकर्ता)", before)
        or re.search(r"(?i)(?:confirmed|aaya|आया|आए|बताते|पुकारते|train|!)", after)
    )


def discover_mentions(text: str) -> tuple[list[Mention], Mention | None]:
    doctors = _doctor_spans(text)
    mentions: list[Mention] = []
    primary: Mention | None = None

    for match in _LABEL_RE.finditer(text):
        role = _label_role(match.group("label"))
        if role in {None, "doctor"}:
            continue
        candidates = _names_in_value(match.group("value"), match.start("value"), role)
        for item in candidates:
            if not _inside((item.start, item.end), doctors):
                mentions.append(item)
                if role == "patient" and primary is None:
                    primary = item

    for match in _EMAIL_HEADER_RE.finditer(text):
        value = match.group("value")
        for display in re.finditer(rf"(?P<name>{_NAME})[ \t]*<[^>]+>", value):
            s = match.start("value") + display.start("name")
            e = match.start("value") + display.end("name")
            surface = display.group("name")
            if not _inside((s, e), doctors) and not _is_non_person(surface):
                mentions.append(Mention(s, e, "person", surface))

    for regex in (_WROTE_RE, _CHAT_RE):
        for match in regex.finditer(text):
            if not _inside(match.span("name"), doctors) and not _is_non_person(match.group("name")):
                mentions.append(Mention(*match.span("name"), "person", match.group("name")))

    # Relation cues in Latin, Devanagari, and Urdu (case-insensitive only on cues, never on _NAME)
    for match in re.finditer(rf"(?i:{_LBOUND}(?:{_RELATION_CUES}){_RBOUND})[ \t:.-]+['\"‘’]?(?P<name>{_NAME})['\"‘’]?", text):
        surface = match.group("name").strip()
        if not _inside(match.span("name"), doctors) and not _is_non_person(surface):
            mentions.append(Mention(*match.span("name"), "relative", surface))

    # Staff cues (excluding non-clinical Sr. Engineer / Sr. Manager / Sr. Citizen)
    for match in re.finditer(rf"(?i:{_LBOUND}(?:{_STAFF_CUES}){_RBOUND})[ \t:.-]+(?P<name>{_NAME})", text):
        prefix_tok = text[match.start():match.start("name")].strip().rstrip(".:").casefold()
        name_text = match.group("name").strip()
        first_word = _canonical(name_text).split()[0] if _canonical(name_text) else ""
        if prefix_tok == "sr" and first_word in _NON_STAFF_SR_ROLES:
            continue
        if _is_non_person(name_text):
            continue
        span = (match.start(), match.end("name"))
        if not _inside(span, doctors):
            mentions.append(Mention(*span, "staff", text[span[0]:span[1]]))

    # Parenthetical staff/role names like "सामाजिक कार्यकर्ता (रीना तिवारी)"
    for match in re.finditer(rf"(?i:(?:{_STAFF_CUES}))[ \t]*\((?P<name>{_NAME})\)", text):
        surface = match.group("name").strip()
        if not _inside(match.span("name"), doctors) and not _is_non_person(surface):
            mentions.append(Mention(*match.span("name"), "staff", surface))

    # Quoted person names ('भगवती', 'चिंटू', "Chintu", "Ajnabi Baba")
    for match in re.finditer(rf"(?P<quote>['\"‘’])(?P<name>{_NAME})(?P=quote)", text):
        surface = match.group("name").strip()
        if not _inside(match.span("name"), doctors) and _is_quoted_person_context(text, match.start("name"), match.end("name"), surface):
            mentions.append(Mention(*match.span("name"), "person", surface))

    return mentions, primary


def _psn(secret: bytes, namespace: str, name: str) -> str:
    digest = hmac.new(secret, b"raksha:text-person\0" + namespace.encode() + b"\0" + _canonical(name).encode(), hashlib.sha256).digest()
    return "PSN-" + base64.b32encode(digest[:10]).decode().rstrip("=")


def prepare_text_records(records: list[PatientRecord] | tuple[PatientRecord, ...], secret: bytes) -> None:
    """Assign a stable patient pseudonym from an explicit in-document name field."""
    for record in records:
        if record.loc != "doc" or not record.fields:
            continue
        text = record.fields[0].raw_value
        _, primary = discover_mentions(text)
        if primary is not None and record.pseudonym_id is None:
            record.pseudonym_id = _psn(secret, str(record.field_metadata.get("record_namespace", "")), primary.surface)
            record.field_metadata["text_primary_name"] = primary.surface


def _name_context(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 40):start]
    after = text[end:min(len(text), end + 25)]
    if re.search(r"(?i)^[ \t]*(?:jagran|puja|snaan|mandir|masjid|temple|river|group|parivar)\b", after):
        return False
    return bool(
        re.search(rf"(?i)(?:{_LBOUND}(?:{_RELATION_CUES}|{_STAFF_CUES}|Mr|Mrs|Ms|Shri|Smt|Dear|naam|नाम){_RBOUND}|['\"‘’]|(?:^|\n)[^\n:]{{0,25}}[:=-])[ \t]*$", before)
        or re.match(r"[ \t]*(?:ji|sahab|ne\b|\(beta\)|\(beti\)|:|['\"‘’])", after, re.IGNORECASE)
    )


def _entity_token_map(mentions: list[Mention], primary: Mention | None, record: PatientRecord) -> tuple[dict[str, str], dict[str, set[str]]]:
    primary_key = _canonical(primary.surface) if primary else ""
    primary_token = record.pseudonym_id or "[PATIENT]"
    entities: dict[str, str] = {}
    role_priority = {"patient": 4, "relative": 3, "staff": 2, "person": 1}
    best_role: dict[str, int] = {}

    for mention in mentions:
        key = _canonical(mention.surface)
        if not key:
            continue
        if primary_key and key == primary_key:
            entities[key] = primary_token
            best_role[key] = 5
            continue
        prio = role_priority.get(mention.role, 1)
        if prio > best_role.get(key, 0):
            best_role[key] = prio
            entities[key] = {"relative": "[RELATIVE]", "staff": "[STAFF]", "person": "[PERSON]", "patient": "[PERSON]"}[mention.role]

    # Link single-word / cross-script / initial mentions to existing multi-word entities
    # without conflating namesakes (e.g., "Bhagwati Prasad Mishra" != "Bhagwatl Prasad Dubey").
    entity_keys = list(entities.keys())
    phonetic_owners: dict[str, set[str]] = {}
    for ekey in entity_keys:
        words = ekey.split()
        for w in words:
            if w in _COMMON_NAME_WORDS:
                continue
            for p in _token_variants(w):
                phonetic_owners.setdefault(p, set()).add(ekey)

    for ekey in list(entities.keys()):
        words = ekey.split()
        if len(words) == 1:
            pkeys = _token_variants(words[0])
            owners = {o for p in pkeys for o in phonetic_owners.get(p, set())}
            if len(owners) == 1:
                owner = next(iter(owners))
                # Only link if the single token isn't already a stronger role, or if owner is primary/relative
                if owner == primary_key or entities[ekey] == "[PERSON]":
                    entities[ekey] = entities[owner]
            elif primary_key and any(p in {_k for w in primary_key.split()[:1] for _k in _token_variants(w)} for p in pkeys):
                # First-name match to primary (e.g. 'भगवती' when primary is 'Bhagwatl Prasad Dubey' and namesake is 'Bhagwati Prasad Mishra')
                if entities[ekey] == "[PERSON]":
                    entities[ekey] = primary_token
    return entities, phonetic_owners


def entity_decisions(record: PatientRecord) -> list[PrivacyDecision]:
    if record.loc != "doc" or not record.fields:
        return []
    text = record.fields[0].raw_value
    path = record.fields[0].field_path
    doctors = _doctor_spans(text)
    mentions, primary = discover_mentions(text)
    entities, _ = _entity_token_map(mentions, primary, record)
    primary_key = _canonical(primary.surface) if primary else ""
    primary_token = record.pseudonym_id or "[PATIENT]"

    candidates: list[tuple[int, int, str]] = []
    for mention in mentions:
        key = _canonical(mention.surface)
        candidates.append((mention.start, mention.end, entities.get(key, "[PERSON]")))

    # Initials + surname matching (e.g., "B.P. Dubey" or "B. P. Dubey" -> primary)
    if primary_key:
        pwords = primary_key.split()
        if len(pwords) >= 2:
            surname = pwords[-1]
            initials = "".join(w[0] for w in pwords[:-1])
            init_re = re.compile(
                rf"(?i){_LBOUND}(?P<init>(?:[A-Z]\.[ \t]*){{1,{len(initials)}}})(?P<sur>{re.escape(surname)}){_RBOUND}"
            )
            for m in init_re.finditer(text):
                if not _inside(m.span(), doctors):
                    got = re.sub(r"[^a-z]", "", m.group("init").casefold())
                    if initials.startswith(got):
                        candidates.append((*m.span(), primary_token))

    # Propagate complete entity mentions (including OCR l<->i variants);
    # bare single tokens (including first names of multi-word entities) require name context.
    single_token_owners: dict[str, str] = {}
    for key, token in entities.items():
        surface_words = key.split()
        if not surface_words:
            continue
        if len(surface_words) >= 2:
            first_w = surface_words[0]
            if len(first_w) >= 4 and first_w not in _NON_PERSON_PHRASES and first_w not in _RELATION_WORDS:
                single_token_owners.setdefault(first_w, token)
            word_pats = []
            for w in surface_words:
                esc = re.escape(w)
                if w.isascii() and ("l" in w or "i" in w):
                    esc = "".join("[il1]" if ch in "il" else re.escape(ch) for ch in w)
                word_pats.append(esc)
            phrase = r"[ \t]+".join(word_pats)
        else:
            phrase = re.escape(surface_words[0])
        for match in re.finditer(rf"{_LBOUND}{phrase}{_RBOUND}", text, re.IGNORECASE):
            if _inside(match.span(), doctors):
                continue
            if len(surface_words) == 1:
                word = surface_words[0]
                if word in _COMMON_NAME_WORDS and not _name_context(text, *match.span()):
                    continue
                if not _name_context(text, *match.span()):
                    continue
            candidates.append((*match.span(), token))

    for first_w, token in single_token_owners.items():
        if first_w in _COMMON_NAME_WORDS:
            continue
        for match in re.finditer(rf"{_LBOUND}{re.escape(first_w)}{_RBOUND}", text, re.IGNORECASE):
            if _inside(match.span(), doctors):
                continue
            if text[match.start():match.end()].isascii() and not text[match.start()].isupper():
                continue
            if _name_context(text, *match.span()):
                candidates.append((*match.span(), token))

    # Strip person tokens embedded inside attachment filenames.
    entity_word_tokens: dict[str, str] = {}
    for key, token in entities.items():
        for w in key.split():
            if len(w) >= 4 and w not in _RELATION_WORDS and w not in _NON_PERSON_PHRASES:
                entity_word_tokens[w] = token
                for v in _token_variants(w):
                    entity_word_tokens.setdefault(v, token)

    for att_match in _ATTACHMENT_LINE_RE.finditer(text):
        val = att_match.group("value")
        base = att_match.start("value")
        for tok_m in re.finditer(r"[A-Za-z]{4,30}", val):
            w = tok_m.group(0).casefold()
            tok_rep = entity_word_tokens.get(w)
            if not tok_rep:
                for v in _token_variants(w):
                    if v in entity_word_tokens:
                        tok_rep = entity_word_tokens[v]
                        break
            if tok_rep:
                candidates.append((base + tok_m.start(), base + tok_m.end(), tok_rep))

    selected: list[tuple[int, int, str]] = []
    for start, end, token in sorted(set(candidates), key=lambda item: (item[0], -(item[1] - item[0]), item[2])):
        if _inside((start, end), doctors) or any(start < old_end and old_start < end for old_start, old_end, _ in selected):
            continue
        selected.append((start, end, token))
    return [
        PrivacyDecision(record.record_ref, path, start, end, TransformType.PSEUDONYMIZE, token)
        for start, end, token in selected
    ]


def _clean_digits(value: str) -> str:
    return value.translate(_OCR_DIGITS)


def _full_dates(text: str) -> list[tuple[int, int, datetime, str]]:
    found: list[tuple[int, int, datetime, str]] = []
    patterns = (
        (r"(?<!\d)[0-3OolI|][\dOolI|SsBZz]/[01OolI|][\dOolI|SsBZz]/(?:19|20)?[\dOolI|SsBZz]{2}(?!\d)", "%d/%m/%Y"),
        (r"(?<!\d)[0-3OolI|][\dOolI|SsBZz]-[01OolI|][\dOolI|SsBZz]-(?:19|20)?[\dOolI|SsBZz]{2}(?!\d)", "%d-%m-%Y"),
        (r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)", "%Y-%m-%d"),
        (r"(?<!\d)\d{1,2}[ -](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[ -]\d{4}(?!\d)", None),
    )
    for pattern, fmt in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            cleaned = _clean_digits(match.group(0))
            formats = [fmt] if fmt else ["%d %b %Y", "%d-%b-%Y", "%d %B %Y", "%d-%B-%Y"]
            if fmt in {"%d/%m/%Y", "%d-%m-%Y"} and len(cleaned.rsplit(cleaned[2], 1)[-1]) == 2:
                formats = [fmt.replace("%Y", "%y")]
            for candidate in formats:
                try:
                    parsed = datetime.strptime(cleaned, candidate)
                    found.append((*match.span(), parsed, candidate))
                    break
                except ValueError:
                    pass
    return sorted(found)


def _authoritative_age(text: str, full_dates: list[tuple[int, int, datetime, str]]) -> float | None:
    reference = max((item[2] for item in full_dates), default=None)
    dob_match = re.search(r"(?i)\b(?:DOB|date[ \t]+of[ \t]+birth)[ \t:=-]+([0-3OolI|][\dOolI|SsBZz]/[01OolI|][\dOolI|SsBZz]/(?:19|20)?[\dOolI|SsBZz]{2})", text)
    if dob_match and reference:
        try:
            dob = datetime.strptime(_clean_digits(dob_match.group(1)), "%d/%m/%Y")
            return (reference.date() - dob.date()).days / 365.2425
        except ValueError:
            pass
    stated = re.search(r"(?i)(?<![~\d])(?:age(?:/sex)?|umr)[ \t:=-]*(\d{1,3})[ \t]*(?:Y\b|yrs?\b|years?\b)", text)
    if stated:
        return float(stated.group(1))
    estimated = re.search(r"(?i)~[ \t]*(\d{1,3})(?:[ \t]*(?:Y\b|yrs?\b|years?\b))?", text)
    return float(estimated.group(1)) if estimated else None


def _band(age: float | None, width: int, top: int) -> str:
    if age is None:
        return "[AGE]"
    if age < 1:
        return "<1"
    if age >= top:
        return f"{top}+"
    low = int(age) // width * width
    return f"{low}-{low + width - 1}"


def temporal_decisions(record: PatientRecord, offset: int, age_width: int, age_top: int) -> list[PrivacyDecision]:
    if record.loc != "doc" or not record.fields:
        return []
    text = record.fields[0].raw_value
    path = record.fields[0].field_path
    full = _full_dates(text)
    authoritative_age = _authoritative_age(text, full)
    decisions: list[PrivacyDecision] = []
    occupied: list[tuple[int, int]] = []

    for start, end, parsed, fmt in full:
        shifted = parsed + timedelta(days=offset)
        replacement = shifted.strftime(fmt)
        if re.search(r"(?i)\b(?:DOB|date[ \t]+of[ \t]+birth)\b", text[max(0, start - 25):start]):
            replacement = shifted.strftime(fmt) if authoritative_age is not None and authoritative_age < 2 else str(shifted.year)
        decisions.append(PrivacyDecision(record.record_ref, path, start, end, TransformType.DATE_SHIFT, replacement))
        occupied.append((start, end))

    compact = re.compile(r"(?<!\d)(?P<date>(?:19|20)\d{6})(?!\d)")
    for match in compact.finditer(text):
        try:
            parsed = datetime.strptime(match.group("date"), "%Y%m%d") + timedelta(days=offset)
        except ValueError:
            continue
        decisions.append(PrivacyDecision(record.record_ref, path, *match.span("date"), TransformType.DATE_SHIFT, parsed.strftime("%Y%m%d")))

    # Year-less dates (17/11, 18/11 0600, started 20/11, Monday 3/2)
    # Guard against clinical fractions: MMSE 14/30, x 5/7, after 1/52, BP 100/60.
    clinical_frac_ctx = re.compile(r"(?i)\b(?:MMSE|CDR|GCS|BP|PR|x|for|after|OD|BD|TDS|QID|SOS)[ \t]*$")
    reference_dates = full
    yearless = re.compile(r"(?i)(?:(?P<weekday>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun)[, \t]+)?(?P<date>[0-3]?\d/[01]?\d)(?!/\d)")
    for match in yearless.finditer(text):
        if any(match.start("date") < end and start < match.end("date") for start, end in occupied):
            continue
        before = text[max(0, match.start("date") - 15):match.start("date")]
        if clinical_frac_ctx.search(before):
            continue
        nearest = min(reference_dates, key=lambda item: abs(item[0] - match.start()), default=None)
        if nearest is None:
            continue
        try:
            parsed = datetime.strptime(f"{match.group('date')}/{nearest[2].year}", "%d/%m/%Y") + timedelta(days=offset)
        except ValueError:
            continue
        date_value = f"{parsed.day:02d}/{parsed.month:02d}" if len(match.group("date").split("/")[0]) == 2 else f"{parsed.day}/{parsed.month}"
        weekday = match.group("weekday")
        if weekday:
            date_value = parsed.strftime("%a" if len(weekday) == 3 else "%A") + text[match.end("weekday"):match.start("date")] + date_value
            span = match.span()
        else:
            span = match.span("date")
        decisions.append(PrivacyDecision(record.record_ref, path, *span, TransformType.DATE_SHIFT, date_value))

    # Weekday attached to a full textual/numeric date: recompute it after shifting.
    weekday_full = re.compile(r"(?i)\b(?P<weekday>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun)(?P<sep>,?[ \t]+)(?P<date>\d{1,2}[ \t]+[A-Za-z]{3,9}[ \t]+\d{4})")
    for match in weekday_full.finditer(text):
        try:
            parsed = datetime.strptime(match.group("date"), "%d %b %Y")
        except ValueError:
            try:
                parsed = datetime.strptime(match.group("date"), "%d %B %Y")
            except ValueError:
                continue
        shifted = parsed + timedelta(days=offset)
        date_fmt = "%d %b %Y" if len(match.group("date").split()[1]) == 3 else "%d %B %Y"
        replacement = shifted.strftime("%a" if len(match.group("weekday")) == 3 else "%A") + match.group("sep") + shifted.strftime(date_fmt)
        decisions.append(PrivacyDecision(record.record_ref, path, *match.span(), TransformType.DATE_SHIFT, replacement))

    # Ages use the most authoritative value found in the document.
    age_pattern = re.compile(r"(?i)(?P<approx>~[ \t]*)?(?P<age>\d{1,3})(?P<unit>[ \t]*(?:Y\b|yrs?\b|years?\b))")
    for match in age_pattern.finditer(text):
        context = text[max(0, match.start() - 25):match.start()]
        if not (match.group("approx") or re.search(r"(?i)(?:age(?:/sex)?|umr|estimate\s*(?:was)?)[ \t:=-]*$", context)):
            continue
        decisions.append(PrivacyDecision(record.record_ref, path, match.start("age"), match.end("unit"),
                                         TransformType.GENERALIZE, _band(authoritative_age or float(match.group("age")), age_width, age_top)))

    # Bare estimated ages like "police estimate was ~75" and "(78 M, Belghat)"
    for match in re.finditer(r"(?i)(?:estimate\s*(?:was)?[ \t:=-]*~[ \t]*)(?P<age>\d{1,3})(?![ \t]*(?:Y\b|yrs?\b|years?\b))", text):
        decisions.append(PrivacyDecision(record.record_ref, path, match.start("age"), match.end("age"),
                                         TransformType.GENERALIZE, _band(authoritative_age or float(match.group("age")), age_width, age_top)))
    for match in re.finditer(r"\((?P<age>\d{1,3})[ \t]*/?[ \t]*(?P<sex>[MF])\b", text):
        val = int(match.group("age"))
        if 1 <= val <= 120:
            decisions.append(PrivacyDecision(record.record_ref, path, match.start("age"), match.end("age"),
                                             TransformType.GENERALIZE, _band(float(val), age_width, age_top)))

    festivals = (
        r"Holi|Diwali|Eid(?:-ul-Fitr|-ul-Adha)?|Baisakhi|Christmas|Dussehra|Navratri|"
        r"Kartik[ \t]+Purnima|Chhath|Makar[ \t]+Sankranti|Raksha[ \t]+Bandhan|Janmashtami|"
        r"Shivratri|Maha[ \t]+Shivratri|Ram[ \t]+Navami|Ganesh[ \t]+Chaturthi|Onam|Pongal|Bihu|Gurpurab"
    )
    for match in re.finditer(rf"(?i)\b(?:{festivals})\b(?:[ \t]+(?:ki|ke|on|evening|morning|night|shaam|raat|subah|agle[ \t]+din))?", text):
        decisions.append(PrivacyDecision(record.record_ref, path, *match.span(), TransformType.REDACT, "[EVENT]"))
    return decisions


def structural_text_decisions(record: PatientRecord) -> list[PrivacyDecision]:
    if record.loc != "doc" or not record.fields:
        return []
    text = record.fields[0].raw_value
    path = record.fields[0].field_path
    patterns = (
        (r"(?i)\bhttps?://[^\s<>\[\]\"')]+", "[URL]"),
        (r"(?i)\b(?:retd?\.?[ \t]+)?[A-Za-z -]{3,35}(?:master|engineer|officer|contractor)[^\n;]{0,60}\((?:19|20)\d{2}[–-](?:19|20)\d{2}\)", "[OCCUPATION]"),
        (r"(?i)\b(?:retd?\.?[ \t]+)?[A-Za-z -]{3,35}(?:master|engineer|officer|contractor)[^\n,;]{0,50}(?:19|20)\d{2}[–-](?:19|20)\d{2}", "[OCCUPATION]"),
        (r"(?i)\bSr\.[ \t]+(?:Engineer|Manager|Executive|Officer|Consultant|Director)[^\n;|]{0,40}", "[OCCUPATION]"),
        (r"['\"‘’]?اسٹیشن[ \t]+ماسٹر[ \t]+صاحب['\"‘’]?", "[OCCUPATION]"),
        (r"(?i)\b(?:school|college)[^\n;]{2,60}\bclass[ \t-]*[A-Z0-9-]+", "[SCHOOL]"),
        (r"(?i)\bclass[ \t-]*\d{1,2}[A-Z-]*(?:[ \t]*,[ \t]*[A-Z][A-Za-z. ]{2,40})?", "[SCHOOL]"),
        (r"(?i)\b(?:whatsapp|facebook|telegram|social[- ]media)[ \t]+group(?:[ \t]+[\"'][^\"'\n]{1,60}[\"']|[^\n,;]{1,60})", "[IDENTITY_HINT]"),
        (r"(?i)\bCCTV[^\n,;]{0,50}\b(?:location|near|at)\b[^\n,;]{2,50}", "[ADDRESS]"),
        (r"(?i)\bplatform[ \t]+\d+[ \t]*(?:\([^)\n]{3,50}\)|[ \t,;-]+(?:stall|shop|gate)[ \t]+[A-Z0-9-]+)", "[ADDRESS]"),
        (r"(?i)\b(?:son|daughter|wife|husband|relative)'?s[ \t]+(?:job|work|office)[^\n,;]{2,70}", "[OCCUPATION]"),
        (r"(?i)\bPS[ \t]+[A-Z][A-Za-z]+(?:[ \t]+[A-Z][A-Za-z]+){0,2}", "[ADDRESS]"),
        (r"(?im)^Address[ \t]*:[ \t]*(?P<val>[^\r\n]+)", "[ADDRESS]"),
        (r"(?i)\b(?:Qr\.?|Quarter|H\.?[ \t]*No\.?|House[ \t]+No\.?|Flat)[ \t]*(?:No\.?[ \t]*)?[:#.-]?[ \t]*[A-Z0-9][A-Z0-9/-]{0,20}\b", "[HOUSE_NO]"),
    )
    decisions: list[PrivacyDecision] = []
    for pattern, token in patterns:
        for match in re.finditer(pattern, text):
            start, end = match.span("val") if "val" in match.re.groupindex else match.span()
            decisions.append(PrivacyDecision(record.record_ref, path, start, end, TransformType.GENERALIZE, token))
    return decisions
