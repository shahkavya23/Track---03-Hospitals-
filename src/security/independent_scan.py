"""Independent residual scanner with addressable findings for late redaction."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
import unicodedata

TOKENS = frozenset({
    "PATIENT", "RELATIVE", "PERSON", "STAFF", "PHONE", "AADHAAR", "PAN",
    "ABHA", "DL", "VOTER_ID", "PASSPORT", "INSURANCE", "EMAIL", "UPI",
    "BANK_ACCOUNT", "IFSC", "PMJAY", "DONOR_ID", "IP", "USERNAME",
    "VEHICLE", "GPS", "CASE_NO", "ID_MARK", "SCHOOL", "OCCUPATION",
    "ADDRESS", "DATE", "AGE", "IDENTITY_HINT", "REDACTED", "PPO",
    "SENIOR_CARD", "AUTH_REF", "URL", "HOUSE_NO", "CCTV_ID", "EVENT",
})


@dataclass(frozen=True, slots=True)
class ScanFinding:
    category: str
    start: int
    end: int
    replacement: str


_NUMBER_WORDS = (
    r"zero|one|two|three|four|five|six|seven|eight|nine|oh|"
    r"shunya|ek|do|teen|char|chaar|paanch|panch|chhe|che|saat|aath|nau|"
    r"शून्य|एक|दो|तीन|चार|पाँच|पांच|छह|सात|आठ|नौ"
)


def _searchable_with_map(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    offsets: list[int] = []
    for pos, char in enumerate(text):
        if char in "\u200b\u200c\u200d\ufeff":
            continue
        for item in unicodedata.normalize("NFKC", char):
            item = str(unicodedata.digit(item)) if item.isdecimal() else item
            chars.append(item)
            offsets.append(pos)
    searchable = "".join(chars)
    # OCR confusables are folded only inside digit-dominant tokens.  Ordinary
    # words (including names) are never modified by this view.
    confusables = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1",
                                 "|": "1", "S": "5", "s": "5", "B": "8",
                                 "Z": "2", "z": "2"})
    folded = list(searchable)
    for match in re.finditer(r"[A-Za-z0-9|]+", searchable):
        token = match.group(0)
        prefix_match = re.match(r"^([A-Za-z]+)\d+$", token)
        if prefix_match and any(ch not in "OoIl|SsBZz" for ch in prefix_match.group(1)):
            continue
        digit_like = sum(ch.isdigit() or ch in "OoIl|SsBZz" for ch in token)
        actual_digits = sum(ch.isdigit() for ch in token)
        if actual_digits >= 1 and len(token) >= 3 and digit_like / len(token) >= .70:
            replacement = token.translate(confusables)
            folded[match.start():match.end()] = replacement
    return "".join(folded), offsets


def _raw_span(offsets: list[int], start: int, end: int) -> tuple[int, int]:
    return offsets[start], offsets[end - 1] + 1


def _is_lot_context(text: str, start: int) -> bool:
    return bool(re.search(r"(?i)\b(?:lot|batch)\s*(?:no\.?\s*)?$", text[max(0, start - 20):start]))


def scan_findings(text: str) -> list[ScanFinding]:
    """Return deterministic findings without pass-1 spans or learned values."""
    searchable, offsets = _searchable_with_map(text)
    if not searchable:
        return []
    rules: tuple[tuple[str, str, str, int], ...] = (
        ("EMAIL", r"(?i)\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[EMAIL]", 13),
        ("OBFUSCATED_EMAIL", r"(?i)\b[\w.-]+\s+dot\s+[\w.-]+\s+at\s+[\w.-]+\s+dot\s+[A-Za-z]{2,}\b", "[EMAIL]", 11),
        ("UPI", r"(?i)(?<![\w@])[\w.-]{2,}@[A-Za-z][A-Za-z0-9.-]{1,20}(?![\w.])", "[UPI]", 12),
        ("PAN", r"(?i)\b[A-Z]{5}\d{4}[A-Z]\b", "[PAN]", 10),
        ("IFSC", r"(?i)\b[A-Z]{4}0[A-Z0-9]{6}\b", "[IFSC]", 10),
        ("VOTER_ID", r"(?i)\b[A-Z]{3}\d{7}\b", "[VOTER_ID]", 9),
        ("PMJAY", r"(?i)\b(?:PM[- ]?JAY|AYUSHMAN)\s*(?:ID|NO\.?)?\s*[:#-]?\s*[A-Z0-9-]{6,24}\b", "[PMJAY]", 9),
        ("DONOR_ID", r"(?i)\b(?:DONOR|BLOOD\s+DONOR)\s*(?:ID|NO\.?)\s*[:#-]?\s*[A-Z0-9/-]{4,24}\b", "[DONOR_ID]", 9),
        ("PPO", r"(?i)\bPPO\s*(?:NO\.?|NUMBER)?\s*[:#-]?\s*[A-Z0-9][A-Z0-9/-]{4,30}\b", "[PPO]", 9),
        ("SENIOR_CARD", r"(?i)\b(?:SENIOR\s*CITIZEN\s*(?:CARD|ID)?\s*[:#-]?\s*)?SC/[A-Z0-9-]{2,20}/\d{4}/[A-Z0-9-]{2,20}\b", "[SENIOR_CARD]", 9),
        ("AUTH_REF", r"(?i)\b(?:AUTH|BIOMETRIC)\s*[-:#]?\s*[A-Z0-9][A-Z0-9/-]{5,30}\b", "[AUTH_REF]", 9),
        ("POLICE_REPORT", r"(?i)\b(?:GUMSHUDGI(?:\s+REPORT)?|FIR|GD|REPORT)\s*(?:NO\.?|NUMBER)?\s*[:#-]?\s*[A-Z0-9][A-Z0-9/-]{3,30}\b", "[CASE_NO]", 9),
        ("POLICE_BELT", r"(?i)\b(?:RPF\s+)?(?:HC|CT\.?|SI)\s+[A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2}\s*(?:\(\s*)?(?:BELT\s*(?:NO\.?)?\s*)?[:#-]?\s*\d{2,8}\s*\)?", "[STAFF]", 9),
        ("URL", r"(?i)\bhttps?://[^\s<>\[\]\"')]+", "[URL]", 9),
        ("HOUSE_NO", r"(?i)\b(?:QR\.?|QUARTER|H\.?\s*NO\.?|HOUSE\s+NO\.?|FLAT)\s*(?:NO\.?\s*)?[:#.-]?\s*[A-Z0-9][A-Z0-9/-]{0,20}\b", "[HOUSE_NO]", 8),
        ("CCTV_ID", r"(?i)\b(?:RPF\s+)?CCTV\s*(?:CAM(?:ERA)?\s*)?(?:ID|NO\.?)?\s*[:#-]?\s*[A-Z0-9][A-Z0-9/_-]{2,24}(?:\s+(?:AT|@)\s+\d{1,2}[:.]\d{2}(?::\d{2})?)?\b", "[CCTV_ID]", 8),
        ("BANK_ACCOUNT", r"(?i)\b(?:A/?C|ACCOUNT)\s*(?:NO\.?|NUMBER)?\s*[:#-]?\s*\d(?:[ -]?\d){7,17}\b", "[BANK_ACCOUNT]", 9),
        ("AADHAAR", r"(?<!\d)(?:\d{4}[ -]){2}\d{4}(?:[ -]?\d)?(?!\d)", "[AADHAAR]", 8),
        ("MASKED_ID", r"(?i)\bX{4}[ -]?X{4}[ -]?\d{4}\b", "[AADHAAR]", 8),
        ("PHONE", r"(?<![\w])(?:\+\s*\d{1,3}[ -]?(?:\(?\d{1,5}\)?[ -]?)?\d(?:[ ().-]?\d){6,11}|(?:\+?91[ -]?)?[6-9](?:[ .()-]?\d){9}|0\d{2,4}[ -]\d(?:[ .-]?\d){5,7})(?!\d)", "[PHONE]", 7),
        ("GPS", r"(?<!\d)[+-]?(?:[0-8]?\d\.\d{3,}|90\.0{3,})\s*[,/]\s*[+-]?(?:1[0-7]\d\.\d{3,}|180\.0{3,}|\d?\d\.\d{3,})(?!\d)", "[GPS]", 7),
        ("VEHICLE", r"(?i)\b[A-Z]{2}[ -]?\d{1,2}[ -]?[A-Z]{1,3}[ -]?\d{4}\b", "[VEHICLE]", 7),
        ("PIN", r"(?i)\b(?:PIN(?:CODE)?|POSTAL\s+CODE)\s*[:=-]?\s*[1-8]\d{5}(?!\d)", "[ADDRESS]", 7),
        ("RELATIVE", r"(?i)\b(?:s/o|w/o|d/o|b/o|son\s+of|wife\s+of|daughter\s+of)\s+(?!\[)[^\W\d_][^\d,;\n\[\]]{2,60}", "[RELATIVE]", 6),
        ("CHAT_SPEAKER", r"(?im)^\s*\[[^\]\n]{5,40}\]\s*(?!(?:Dr\.?|डॉ\.)\s)(?!\[)(?:[A-Z][\w'.-]*|[\u0600-\u06ff]{2,})(?:\s+(?:[A-Z][\w'.-]*|[\u0600-\u06ff]{2,})){0,3}(?=\s*:)", "[PATIENT]", 6),
        ("SOCIAL_HANDLE", r"(?<![\w@.])@[A-Za-z_][A-Za-z0-9_.]{2,30}\b", "[USERNAME]", 5),
        ("LANDMARK", r"(?i)\b(?:near|opposite|behind|paas|nazdeek)\s+(?!\[)[^,;\n.]{3,60}\b(?:mandir|masjid|ghaat|ghat|sthan|temple|school|station)\b", "[ADDRESS]", 4),
        ("NICKNAME", r"(?i)(?:\b(?:urf|alias|aka)\s+|(?<!\w)@\s*)(?!\[)(?:[A-Z][\w'.-]{1,30}|[\u0600-\u06ff]{2,30})", "[PERSON]", 4),
    )
    candidates: list[tuple[int, int, int, ScanFinding]] = []
    for category, pattern, replacement, priority in rules:
        for match in re.finditer(pattern, searchable):
            start, end = _raw_span(offsets, match.start(), match.end())
            if category == "PHONE" and _is_lot_context(text, start):
                continue
            candidates.append((start, end, priority, ScanFinding(category, start, end, replacement)))
    split_phone = re.compile(
        r"(?i)\b(?:phone|mobile|contact|tel)\s*[:=-]?\s*"
        r"(?P<number>(?:\+\s*\d{1,3}[ -]?)?\d(?:[ ().-]?\d){3,7}\s*\r?\n\s*\d(?:[ ().-]?\d){3,7})(?!\d)"
    )
    for match in split_phone.finditer(searchable):
        start, end = _raw_span(offsets, *match.span('number'))
        digit_count = sum(ch.isdigit() for ch in searchable[match.start('number'):match.end('number')])
        if 8 <= digit_count <= 15:
            candidates.append((start, end, 7, ScanFinding('PHONE_SPLIT', start, end, '[PHONE]')))
    word_re = re.compile(rf"(?i)(?<!\w)(?:{_NUMBER_WORDS}|\d+)(?:(?:[\s,./-]|\band\b|\baur\b)+(?:{_NUMBER_WORDS}|\d+)){{5,14}}(?!\w)")
    for match in word_re.finditer(searchable):
        start, end = _raw_span(offsets, match.start(), match.end())
        fragment = match.group(0)
        digit_count = sum(ch.isdigit() for ch in fragment)
        digit_count += len(re.findall(_NUMBER_WORDS, fragment, re.IGNORECASE))
        if 8 <= digit_count <= 15:
            candidates.append((start, end, 7, ScanFinding("PHONE_WORDS", start, end, "[PHONE]")))

    selected: list[ScanFinding] = []
    for start, end, priority, finding in sorted(candidates, key=lambda x: (-x[2], x[0], -(x[1] - x[0]), x[1])):
        if any(start < old.end and old.start < end for old in selected):
            continue
        selected.append(finding)
    return sorted(selected, key=lambda item: (item.start, item.end, item.category))


def scan(text: str) -> dict[str, int]:
    findings = Counter(item.category for item in scan_findings(text))
    searchable, _ = _searchable_with_map(text)
    for token in re.findall(r"\[([A-Z][A-Z_-]*)\]", searchable):
        if token not in TOKENS:
            findings["UNKNOWN_TOKEN"] += 1
    return {key: value for key, value in sorted(findings.items()) if value}
