# Purpose: Deterministic Devanagari-to-Latin transliteration with exact original-offset preservation.
"""Offline Devanagari-to-Latin transliteration with offset tracking."""

from __future__ import annotations

from .unicode_map import IndexedText, normalize_with_offset_map

_VIRAMA = "\u094d"
_NUKTA = "\u093c"
_ANUSVARA = "\u0902"
_CHANDRABINDU = "\u0901"
_VISARGA = "\u0903"

# Precomposed nukta codepoints normalized to base + nukta internally for uniform handling.
_NUKTA_DECOMPOSITION: dict[str, tuple[str, str]] = {
    "\u0958": ("\u0915", _NUKTA),  # क़
    "\u0959": ("\u0916", _NUKTA),  # ख़
    "\u095a": ("\u0917", _NUKTA),  # ग़
    "\u095b": ("\u091c", _NUKTA),  # ज़
    "\u095c": ("\u0921", _NUKTA),  # ड़
    "\u095d": ("\u0922", _NUKTA),  # ढ़
    "\u095e": ("\u092b", _NUKTA),  # फ़
    "\u095f": ("\u092f", _NUKTA),  # य़
}

_INDEPENDENT_VOWELS: dict[str, str] = {
    "अ": "a",
    "आ": "aa",
    "इ": "i",
    "ई": "ee",
    "उ": "u",
    "ऊ": "oo",
    "ऋ": "ri",
    "ए": "e",
    "ऐ": "ai",
    "ओ": "o",
    "औ": "au",
    "ऑ": "o",
    "ॲ": "a",
    "ऍ": "e",
}

_CONSONANTS: dict[str, str] = {
    "क": "k",
    "ख": "kh",
    "ग": "g",
    "घ": "gh",
    "ङ": "ng",
    "च": "ch",
    "छ": "chh",
    "ज": "j",
    "झ": "jh",
    "ञ": "ny",
    "ट": "t",
    "ठ": "th",
    "ड": "d",
    "ढ": "dh",
    "ण": "n",
    "त": "t",
    "थ": "th",
    "द": "d",
    "ध": "dh",
    "न": "n",
    "प": "p",
    "फ": "ph",
    "ब": "b",
    "भ": "bh",
    "म": "m",
    "य": "y",
    "र": "r",
    "ल": "l",
    "ळ": "l",
    "व": "v",
    "श": "sh",
    "ष": "sh",
    "स": "s",
    "ह": "h",
}

_NUKTA_CONSONANTS: dict[str, str] = {
    "क": "q",
    "ख": "kh",
    "ग": "gh",
    "ज": "z",
    "ड": "r",
    "ढ": "rh",
    "फ": "f",
    "य": "y",
}

_MATRAS: dict[str, str] = {
    "\u093e": "a",   # ा
    "\u093f": "i",   # ि
    "\u0940": "ee",  # ी
    "\u0941": "u",   # ु
    "\u0942": "oo",  # ू
    "\u0943": "ri",  # ृ
    "\u0945": "e",   # ॅ
    "\u0947": "e",   # े
    "\u0948": "ai",  # ै
    "\u0949": "o",   # ॉ
    "\u094b": "o",   # ो
    "\u094c": "au",  # ौ
}

_LABIAL_CONSONANTS = frozenset({"प", "फ", "ब", "भ", "म"})
_SPECIAL_CONJUNCTS: dict[tuple[str, str], str] = {
    ("क", "ष"): "ksh",
    ("त", "र"): "tr",
    ("ज", "ञ"): "gy",
    ("श", "र"): "shr",
}


def _is_devanagari(ch: str) -> bool:
    return "\u0900" <= ch <= "\u097f"


def _is_devanagari_letter_or_mark(ch: str) -> bool:
    return (
        ch in _CONSONANTS
        or ch in _INDEPENDENT_VOWELS
        or ch in _MATRAS
        or ch in _NUKTA_DECOMPOSITION
        or ch in (_VIRAMA, _NUKTA, _ANUSVARA, _CHANDRABINDU, _VISARGA)
    )


def _base_and_nukta(text: str, idx: int) -> tuple[str, bool, int]:
    """Read consonant at `idx`, returning `(base_char, has_nukta, next_idx)`."""
    ch = text[idx]
    if ch in _NUKTA_DECOMPOSITION:
        base, _ = _NUKTA_DECOMPOSITION[ch]
        return base, True, idx + 1
    if idx + 1 < len(text) and text[idx + 1] == _NUKTA:
        return ch, True, idx + 2
    return ch, False, idx + 1


def transliterate_with_map(text: str) -> IndexedText:
    """Transliterate Devanagari text to canonical Latin while preserving original offsets."""
    if not text:
        return IndexedText(original="", normalized="", orig_starts=(), orig_ends=(), provenance=())

    base_indexed = normalize_with_offset_map(text, fold_whitespace=True, fold_case=False)
    norm_str = base_indexed.normalized
    n = len(norm_str)

    out_chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    provenance = set(base_indexed.provenance)

    def emit(piece: str, norm_span_start: int, norm_span_end: int) -> None:
        orig_s, orig_e = base_indexed.to_original_span(
            norm_span_start, norm_span_end, expand_combining=False
        )
        for ch in piece:
            out_chars.append(ch)
            starts.append(orig_s)
            ends.append(orig_e)

    i = 0
    while i < n:
        ch = norm_str[i]

        # Independent vowels
        if ch in _INDEPENDENT_VOWELS:
            provenance.add("DEVANAGARI_TRANSLIT")
            emit(_INDEPENDENT_VOWELS[ch], i, i + 1)
            i += 1
            continue

        # Consonants (including precomposed nukta or base + nukta)
        base_ch, has_nukta, after_base = _base_and_nukta(norm_str, i)
        if base_ch in _CONSONANTS:
            provenance.add("DEVANAGARI_TRANSLIT")
            unit_start = i
            consonant_latin = (
                _NUKTA_CONSONANTS.get(base_ch, _CONSONANTS[base_ch])
                if has_nukta
                else _CONSONANTS[base_ch]
            )
            cursor = after_base

            # Check special conjuncts like क्ष, त्र, ज्ञ, श्र
            if not has_nukta and cursor < n and norm_str[cursor] == _VIRAMA and cursor + 1 < n:
                next_base, next_nukta, after_next = _base_and_nukta(norm_str, cursor + 1)
                if not next_nukta and (base_ch, next_base) in _SPECIAL_CONJUNCTS:
                    consonant_latin = _SPECIAL_CONJUNCTS[(base_ch, next_base)]
                    cursor = after_next

            # Check vowel sign / virama following the consonant (or conjunct)
            if cursor < n and norm_str[cursor] == _VIRAMA:
                # Virama suppresses inherent 'a'
                emit(consonant_latin, unit_start, cursor + 1)
                i = cursor + 1
                continue

            if cursor < n and norm_str[cursor] in _MATRAS:
                matra = norm_str[cursor]
                emit(consonant_latin + _MATRAS[matra], unit_start, cursor + 1)
                i = cursor + 1
                continue

            # No explicit matra or virama: apply Hindi schwa deletion at word end.
            at_word_end = cursor >= n or not _is_devanagari_letter_or_mark(norm_str[cursor])
            # Also drop final inherent schwa before trailing anusvara only if desired; keep before anusvara (e.g. सिंह).
            if at_word_end and len(out_chars) > 0 and _is_devanagari(norm_str[unit_start - 1] if unit_start > 0 else ""):
                emit(consonant_latin, unit_start, cursor)
            else:
                emit(consonant_latin + "a", unit_start, cursor)
            i = cursor
            continue

        if ch == _ANUSVARA:
            provenance.add("DEVANAGARI_TRANSLIT")
            next_ch = norm_str[i + 1] if i + 1 < n else ""
            nasal = "m" if next_ch in _LABIAL_CONSONANTS else "n"
            emit(nasal, i, i + 1)
            i += 1
            continue

        if ch == _CHANDRABINDU:
            provenance.add("DEVANAGARI_TRANSLIT")
            emit("n", i, i + 1)
            i += 1
            continue

        if ch == _VISARGA:
            provenance.add("DEVANAGARI_TRANSLIT")
            emit("h", i, i + 1)
            i += 1
            continue

        if ch == "।" or ch == "॥":
            provenance.add("DEVANAGARI_TRANSLIT")
            emit(".", i, i + 1)
            i += 1
            continue

        # Stray matra or non-Devanagari character
        if ch in _MATRAS:
            provenance.add("DEVANAGARI_TRANSLIT")
            emit(_MATRAS[ch], i, i + 1)
            i += 1
            continue

        emit(ch, i, i + 1)
        i += 1

    return IndexedText(
        original=text,
        normalized="".join(out_chars),
        orig_starts=tuple(starts),
        orig_ends=tuple(ends),
        provenance=tuple(sorted(provenance)),
    )


def transliterate_devanagari(text: str) -> str:
    """Convenience wrapper returning the transliterated Latin string."""
    return transliterate_with_map(text).normalized
