"""Encoding sniffing, BOM removal, binary rejection, and strict UTF-8 normalization."""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from typing import Sequence

from charset_normalizer import from_bytes

from .errors import IngestionQuarantineError

_BOM_ENCODINGS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)

_DEFAULT_FALLBACKS: tuple[str, ...] = ("cp1252", "iso-8859-1")


@dataclass(frozen=True, slots=True)
class DecodedText:
    """Normalized UTF-8 text alongside detected source encoding."""

    text: str
    encoding: str


def _has_excessive_control_chars(text: str) -> bool:
    """Detect binary garbage disguised inside decoded text."""
    if not text:
        return False
    disallowed = sum(
        1
        for ch in text
        if ord(ch) < 32 and ch not in ("\n", "\r", "\t")
    )
    return (disallowed / len(text)) > 0.02 or "\x00" in text


def decode_bytes_to_utf8(
    raw_bytes: bytes,
    fallbacks: Sequence[str] = _DEFAULT_FALLBACKS,
) -> DecodedText:
    """Decode arbitrary raw bytes safely to clean UTF-8 text or quarantine."""
    if not raw_bytes:
        return DecodedText(text="", encoding="utf-8")

    # 1. Explicit BOM check (handles UTF-8-SIG, UTF-16, UTF-32 deterministically).
    for bom, encoding in _BOM_ENCODINGS:
        if raw_bytes.startswith(bom):
            try:
                text = raw_bytes.decode(encoding, errors="strict")
            except UnicodeDecodeError as exc:
                raise IngestionQuarantineError("malformed encoding with bom") from exc
            text = text.lstrip("\ufeff")
            if _has_excessive_control_chars(text):
                raise IngestionQuarantineError("binary content detected")
            return DecodedText(text=text.replace("\r\n", "\n").replace("\r", "\n"), encoding=encoding)

    # 2. Reject raw NUL bytes unless charset_normalizer confirms BOM-less UTF-16/UTF-32.
    contains_nul = b"\x00" in raw_bytes

    # 3. Fast path: strict UTF-8 (covers modern English, Devanagari Hindi, Hinglish).
    if not contains_nul:
        try:
            text = raw_bytes.decode("utf-8", errors="strict")
            if _has_excessive_control_chars(text):
                raise IngestionQuarantineError("binary content detected")
            return DecodedText(text=text.replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8")
        except UnicodeDecodeError as exc:
            # If valid multibyte UTF-8 text is cut off mid-character at EOF, quarantine
            # instead of letting statistical guessing misread it as CJK/Shift-JIS.
            if (
                exc.reason == "unexpected end of data"
                and exc.end == len(raw_bytes)
                and any(byte >= 0x80 for byte in raw_bytes[: exc.start])
            ):
                raise IngestionQuarantineError("truncated utf-8 encoding") from exc

    # 4. Statistical charset detection via charset-normalizer.
    best = from_bytes(raw_bytes).best()
    if best is not None:
        detected_enc = best.encoding
        if contains_nul and not detected_enc.startswith(("utf_16", "utf_32")):
            raise IngestionQuarantineError("binary content detected")
        try:
            text = str(best)
            if not _has_excessive_control_chars(text):
                return DecodedText(
                    text=text.replace("\r\n", "\n").replace("\r", "\n"),
                    encoding=detected_enc,
                )
        except UnicodeDecodeError:
            pass

    if contains_nul:
        raise IngestionQuarantineError("binary content detected")

    # 5. Deterministic legacy single-byte fallbacks.
    for enc in fallbacks:
        try:
            text = raw_bytes.decode(enc, errors="strict")
            if not _has_excessive_control_chars(text):
                return DecodedText(
                    text=text.replace("\r\n", "\n").replace("\r", "\n"),
                    encoding=enc,
                )
        except UnicodeDecodeError:
            continue

    raise IngestionQuarantineError("undecodable character encoding")
