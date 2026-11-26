# Purpose: Unicode NFKC/digit normalization with exact character offset mapping back to original text.
"""Unicode normalization and exact original-offset mapping for RAKSHA."""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata

# Invisible format characters that frequently break naive regex/token matching.
_INVISIBLE_FORMAT_CHARS = frozenset({
    "\u00ad",  # Soft hyphen
    "\u200b",  # Zero-width space
    "\u200c",  # Zero-width non-joiner
    "\u200d",  # Zero-width joiner
    "\u200e",  # Left-to-right mark
    "\u200f",  # Right-to-left mark
    "\u202a",  # LRE
    "\u202b",  # RLE
    "\u202c",  # PDF
    "\u202d",  # LRO
    "\u202e",  # RLO
    "\ufeff",  # BOM / ZWNBSP
})

# Devanagari digits (U+0966..U+096F) -> ASCII '0'..'9'.
_DEVANAGARI_DIGIT_OFFSET = ord("0") - 0x0966
_COMBINING_CATEGORIES = frozenset({"Mn", "Mc"})


@dataclass(frozen=True, slots=True)
class IndexedText:
    """Normalized or transliterated text paired with per-character original bounds.

    Every index `i` in `normalized` corresponds to the half-open slice
    `original[orig_starts[i] : orig_ends[i]]` using Python UTF-8 Unicode
    codepoint indices.
    """

    original: str
    normalized: str
    orig_starts: tuple[int, ...]
    orig_ends: tuple[int, ...]
    provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        n = len(self.normalized)
        if len(self.orig_starts) != n or len(self.orig_ends) != n:
            raise ValueError("IndexedText offset map lengths must match normalized length")

    def to_original_span(
        self,
        norm_start: int,
        norm_end: int,
        *,
        expand_combining: bool = True,
    ) -> tuple[int, int]:
        """Map a normalized `[norm_start, norm_end)` span back to `original` indices."""
        if norm_start < 0 or norm_end < norm_start or norm_end > len(self.normalized):
            raise ValueError("Normalized span indices are out of range")
        if norm_start == norm_end:
            if norm_start < len(self.orig_starts):
                pos = self.orig_starts[norm_start]
            elif self.orig_ends:
                pos = self.orig_ends[-1]
            else:
                pos = 0
            return pos, pos

        orig_start = self.orig_starts[norm_start]
        orig_end = self.orig_ends[norm_end - 1]

        if expand_combining:
            # Never start mid-combining-mark or truncate trailing combining marks (matras/halant).
            while orig_start > 0 and unicodedata.category(self.original[orig_start]) in _COMBINING_CATEGORIES:
                orig_start -= 1
            orig_len = len(self.original)
            while orig_end < orig_len and unicodedata.category(self.original[orig_end]) in _COMBINING_CATEGORIES:
                orig_end += 1

        return orig_start, orig_end

    def slice_original(self, norm_start: int, norm_end: int) -> str:
        """Return the exact substring in `original` covered by `[norm_start, norm_end)`."""
        start, end = self.to_original_span(norm_start, norm_end)
        return self.original[start:end]


def _is_horizontal_space(ch: str) -> bool:
    return ch in (" ", "\t", "\u00a0", "\u2000", "\u2001", "\u2002", "\u2003", "\u2009", "\u202f", "\u3000")


def normalize_with_offset_map(
    text: str,
    *,
    fold_whitespace: bool = True,
    fold_case: bool = False,
    map_devanagari_digits: bool = True,
) -> IndexedText:
    """Normalize Unicode compatibility forms, digits, and invisible chars with exact offset maps."""
    if not text:
        return IndexedText(original="", normalized="", orig_starts=(), orig_ends=(), provenance=())

    out_chars: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    provenance: set[str] = set()

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]

        if ch in _INVISIBLE_FORMAT_CHARS or unicodedata.category(ch) == "Cf":
            provenance.add("STRIP_INVISIBLE")
            i += 1
            continue

        if fold_whitespace and _is_horizontal_space(ch):
            run_start = i
            i += 1
            while i < n and (
                _is_horizontal_space(text[i])
                or text[i] in _INVISIBLE_FORMAT_CHARS
                or unicodedata.category(text[i]) == "Cf"
            ):
                if text[i] in _INVISIBLE_FORMAT_CHARS:
                    provenance.add("STRIP_INVISIBLE")
                i += 1
            if i - run_start > 1 or ch != " ":
                provenance.add("FOLD_WHITESPACE")
            out_chars.append(" ")
            starts.append(run_start)
            ends.append(i)
            continue

        if map_devanagari_digits and "\u0966" <= ch <= "\u096f":
            ascii_digit = chr(ord(ch) + _DEVANAGARI_DIGIT_OFFSET)
            provenance.add("DEVANAGARI_DIGITS")
            out_chars.append(ascii_digit)
            starts.append(i)
            ends.append(i + 1)
            i += 1
            continue

        # Normalize compatibility/fullwidth forms per codepoint so provenance stays exact.
        norm_piece = unicodedata.normalize("NFKC", ch)
        if norm_piece != ch:
            provenance.add("NFKC")
        if fold_case:
            lowered = norm_piece.lower()
            if lowered != norm_piece:
                provenance.add("CASE_FOLD")
            norm_piece = lowered

        for out_ch in norm_piece:
            out_chars.append(out_ch)
            starts.append(i)
            ends.append(i + 1)
        i += 1

    return IndexedText(
        original=text,
        normalized="".join(out_chars),
        orig_starts=tuple(starts),
        orig_ends=tuple(ends),
        provenance=tuple(sorted(provenance)),
    )
