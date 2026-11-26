# Purpose: Multilingual Indian person-name normalization and phonetic key generation for Member 3 linkage.
"""Indian person-name normalization and cross-script phonetic key generation."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .transliteration import transliterate_with_map

# Leading/trailing honorifics and particles (never strip genuine surname tokens like Devi/Kumar).
HONORIFIC_TOKENS = frozenset({
    "mr",
    "mrs",
    "ms",
    "miss",
    "master",
    "smt",
    "shri",
    "sri",
    "shree",
    "dr",
    "prof",
    "ji",
    "sahab",
    "sahib",
    "saheb",
    "janab",
    "babu",
    "bhai",
    "behen",
    "behna",
    "kumari",
    "km",
    "late",
    "sh",
})

# Common Indian name abbreviations -> canonical Latin expansion.
ABBREVIATION_MAP: dict[str, str] = {
    "mohd": "mohammad",
    "md": "mohammad",
    "mhd": "mohammad",
    "mohammed": "mohammad",
    "muhammad": "mohammad",
    "muhammed": "mohammad",
    "mohamad": "mohammad",
    "kr": "kumar",
    "kmr": "kumar",
    "pd": "prasad",
    "prsd": "prasad",
    "ch": "chandra",
    "sk": "sheikh",
    "shaikh": "sheikh",
    "shk": "sheikh",
    "st": "sant",
}

_NON_ALNUM_SPACE_RE = re.compile(r"[^a-z0-9\s]+")
_MULTI_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class NormalizedName:
    """Canonical internal name representation for cross-script linkage evidence."""

    canonical_name: str
    name_key: str
    tokens: tuple[str, ...]
    provenance: tuple[str, ...]


def phonetic_token_key(token: str) -> str:
    """Generate an Indian-aware phonetic consonant skeleton for a Latin name token.

    Maps cross-script spelling variations (e.g. `Mohammad`/`Mohd`/`मोहम्मद`,
    `Meera`/`Mira`/`मीरा`, `Arif`/`Aarif`/`आरिफ`, `Vikas`/`Bikas`) into a
    compact, deterministic ASCII key.
    """
    cleaned = re.sub(r"[^a-z0-9]", "", token.lower())
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned.upper()

    # Step 1: Canonicalize common Indian vowel & digraph equivalences.
    s = cleaned
    digraph_replacements = (
        ("chh", "c"),
        ("ksh", "x"),
        ("sh", "s"),
        ("bh", "b"),
        ("ph", "f"),
        ("th", "t"),
        ("dh", "d"),
        ("kh", "k"),
        ("gh", "g"),
        ("jh", "j"),
        ("aa", "a"),
        ("ee", "i"),
        ("oo", "u"),
        ("ae", "e"),
        ("ai", "e"),
        ("au", "o"),
        ("ou", "o"),
        ("ri", "r"),
    )
    for src, dst in digraph_replacements:
        s = s.replace(src, dst)

    # Step 2: Single-letter phonetic equivalences.
    char_map = str.maketrans({
        "q": "k",
        "z": "j",
        "v": "w",
        "c": "k",
    })
    s = s.translate(char_map)

    # Step 3: Collapse consecutive duplicate letters.
    deduped: list[str] = []
    for ch in s:
        if not deduped or deduped[-1] != ch:
            deduped.append(ch)
    s = "".join(deduped)

    # Step 4: Keep initial character (even if vowel) + non-vowel skeleton.
    vowels = frozenset({"a", "e", "i", "o", "u"})
    skeleton = [s[0]] + [ch for ch in s[1:] if ch not in vowels]
    return "".join(skeleton).upper()


def normalize_person_name(raw_name: str) -> NormalizedName:
    """Normalize an English, Hindi, or Hinglish person name into canonical + phonetic forms."""
    if not raw_name or not raw_name.strip():
        return NormalizedName(canonical_name="", name_key="", tokens=(), provenance=())

    translit = transliterate_with_map(raw_name)
    provenance = set(translit.provenance)

    lowered = translit.normalized.lower()
    # Replace punctuation/hyphens with spaces (keeps "Padmini-Devi" as two tokens).
    cleaned = _NON_ALNUM_SPACE_RE.sub(" ", lowered)
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned).strip()

    raw_tokens = [tok for tok in cleaned.split(" ") if tok]
    filtered_tokens: list[str] = []
    for tok in raw_tokens:
        if tok in HONORIFIC_TOKENS:
            provenance.add("STRIP_HONORIFIC")
            continue
        expanded = ABBREVIATION_MAP.get(tok, tok)
        if expanded != tok:
            provenance.add("EXPAND_ABBREV")
        filtered_tokens.append(expanded)

    if not filtered_tokens:
        return NormalizedName(
            canonical_name="",
            name_key="",
            tokens=(),
            provenance=tuple(sorted(provenance)),
        )

    canonical_name = " ".join(filtered_tokens)
    phonetic_parts = sorted({
        key for tok in filtered_tokens if (key := phonetic_token_key(tok))
    })
    if len(filtered_tokens) > 1:
        provenance.add("SORTED_PHONETIC_KEY")
    name_key = "_".join(phonetic_parts)

    return NormalizedName(
        canonical_name=canonical_name,
        name_key=name_key,
        tokens=tuple(filtered_tokens),
        provenance=tuple(sorted(provenance)),
    )
