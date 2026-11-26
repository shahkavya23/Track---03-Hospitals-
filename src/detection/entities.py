# Purpose: Within-record multilingual name propagation and cross-script phonetic entity matching.
"""Intra-record name propagation and cross-script entity matching."""

from __future__ import annotations

import re
from typing import Sequence

from src.contracts import DetectionSpan, PatientRecord, SpanRole
from src.detection.normalization import (
    IndexedText,
    normalize_person_name,
    normalize_with_offset_map,
    phonetic_token_key,
    transliterate_devanagari,
)

# Common words that must never be propagated alone as a name token.
_NON_PROPAGATABLE_TOKENS = frozenset({
    "patient", "doctor", "hospital", "clinic", "ward", "fever", "cough", "pain",
    "care", "note", "notes", "date", "male", "female", "indian", "delhi", "mumbai",
    "ramipril", "dolo", "paracetamol", "insulin", "parkinson", "addison", "alzheimer",
})

# Tokenize Latin words OR Devanagari words (excluding Devanagari digits/danda).
_WORD_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'’-]{1,24}|[\u0901-\u0963\u0970-\u097f]{2,24}")


def _is_dr_prefixed(text: str, start: int) -> bool:
    prefix = text[max(0, start - 10) : start].lower()
    return bool(re.search(r"(?:dr\.?|डॉ\.?|डॉक्टर)\s*$", prefix))


def _overlaps_existing(field_path: str, s: int, e: int, existing: Sequence[DetectionSpan]) -> bool:
    return any(
        sp.field_path == field_path and not sp.is_header_detection and s < sp.end and sp.start < e
        for sp in existing
    )


def propagate_known_names_in_record(
    record: PatientRecord,
    seed_spans: Sequence[DetectionSpan],
) -> list[DetectionSpan]:
    """Propagate confirmed patient/relative names across all narrative fields in `record`.

    Uses both exact surface matching and per-token phonetic key sequence matching so
    cross-script mentions (e.g., `"Mohammad Arif"` <-> `"मोहम्मद आरिफ"`) link cleanly
    to exact original UTF-8 spans without overriding primary detections.
    """
    fields_by_path = {node.field_path: node for node in record.fields}

    seeds: list[tuple[str, tuple[str, ...], tuple[str, ...], str]] = []
    for span in seed_spans:
        if span.is_header_detection or span.role != SpanRole.DIRECT_PII:
            continue
        if span.category not in {"PATIENT_NAME", "PERSON_NAME", "RELATIVE_NAME"}:
            continue
        node = fields_by_path.get(span.field_path)
        if node is None or span.end > len(node.raw_value):
            continue
        surface = node.raw_value[span.start : span.end].strip()
        norm_name = normalize_person_name(surface)
        if surface and norm_name.tokens:
            phon_seq = tuple(
                key for tok in norm_name.tokens if (key := phonetic_token_key(tok))
            )
            if phon_seq:
                seeds.append((surface, norm_name.tokens, phon_seq, span.category))

    if not seeds:
        return []

    propagated: list[DetectionSpan] = []

    for node in record.fields:
        raw = node.raw_value
        if not raw or not raw.strip():
            continue
        if node.is_structured_key and node.header_key.lower() in {
            "resourcetype", "system", "code", "status", "use", "reference", "fullurl",
            "uhid", "mrn", "abha", "aadhaar", "pan",
        }:
            continue

        indexed_norm: IndexedText = normalize_with_offset_map(raw)
        # Pre-tokenize words with exact original bounds and phonetic keys.
        word_entries: list[tuple[int, int, str, str]] = []
        for wm in _WORD_TOKEN_RE.finditer(indexed_norm.normalized):
            ws, we = indexed_norm.to_original_span(wm.start(), wm.end())
            word_raw = wm.group(0)
            latin_word = word_raw if word_raw.isascii() else transliterate_devanagari(word_raw)
            pkey = phonetic_token_key(latin_word)
            word_entries.append((ws, we, word_raw, pkey))

        for surface, canon_tokens, phon_seq, category in seeds:
            # A. Exact surface match (case-insensitive for Latin).
            escaped_surface = re.escape(surface)
            for m in re.finditer(rf"(?<!\w){escaped_surface}(?!\w)", indexed_norm.normalized, re.IGNORECASE):
                s, e = indexed_norm.to_original_span(m.start(), m.end())
                if _is_dr_prefixed(raw, s) or _overlaps_existing(node.field_path, s, e, seed_spans):
                    continue
                propagated.append(
                    DetectionSpan(
                        record_ref=record.record_ref,
                        field_path=node.field_path,
                        start=s,
                        end=e,
                        category=category,
                        role=SpanRole.DIRECT_PII,
                        confidence=0.91,
                        detector_source="entity_propagation_exact",
                    )
                )

            # B. Cross-script phonetic token sequence match (handles "Mohammad Arif" <-> "मोहम्मद आरिफ").
            seq_len = len(phon_seq)
            if seq_len >= 2 and len(word_entries) >= seq_len:
                for idx in range(len(word_entries) - seq_len + 1):
                    window = word_entries[idx : idx + seq_len]
                    if tuple(item[3] for item in window) == phon_seq:
                        s, e = window[0][0], window[-1][1]
                        if _is_dr_prefixed(raw, s) or _overlaps_existing(node.field_path, s, e, seed_spans):
                            continue
                        propagated.append(
                            DetectionSpan(
                                record_ref=record.record_ref,
                                field_path=node.field_path,
                                start=s,
                                end=e,
                                category=category,
                                role=SpanRole.DIRECT_PII,
                                confidence=0.89,
                                detector_source="entity_propagation_xscript",
                            )
                        )

            # C. Unambiguous single-token propagation (token >= 4 chars, not a stopword).
            for tok in canon_tokens:
                if len(tok) < 4 or tok in _NON_PROPAGATABLE_TOKENS:
                    continue
                tok_pkey = phonetic_token_key(tok)
                for ws, we, word_raw, pkey in word_entries:
                    if pkey != tok_pkey:
                        continue
                    if word_raw.isascii() and not word_raw[0].isupper():
                        continue
                    if _is_dr_prefixed(raw, ws) or _overlaps_existing(node.field_path, ws, we, seed_spans):
                        continue
                    propagated.append(
                        DetectionSpan(
                            record_ref=record.record_ref,
                            field_path=node.field_path,
                            start=ws,
                            end=we,
                            category=category,
                            role=SpanRole.DIRECT_PII,
                            confidence=0.83,
                            detector_source="entity_propagation_token",
                        )
                    )

    return propagated
