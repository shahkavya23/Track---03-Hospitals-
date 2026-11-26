# Purpose: Synthetic unit tests for Unicode offset mapping, Devanagari transliteration, name keys, phones, and dates.
"""Phase 2 tests for multilingual normalization and offset preservation."""

from __future__ import annotations

import unittest

from src.detection.normalization import (
    normalize_date,
    normalize_person_name,
    normalize_phone,
    normalize_with_offset_map,
    transliterate_devanagari,
    transliterate_with_map,
)


class UnicodeOffsetMapTests(unittest.TestCase):
    def test_invisible_chars_and_whitespace_preserve_original_slice(self) -> None:
        raw = "Patient:\u200b   Mohd.\u200d  Arif"
        indexed = normalize_with_offset_map(raw)
        self.assertEqual(indexed.normalized, "Patient: Mohd. Arif")

        start = indexed.normalized.index("Mohd.")
        end = start + len("Mohd. Arif")
        orig_start, orig_end = indexed.to_original_span(start, end)
        self.assertEqual(raw[orig_start:orig_end], "Mohd.\u200d  Arif")

    def test_nfkc_compatibility_and_devanagari_digits_map_to_original(self) -> None:
        raw = "ID: 𝐴𝑟𝑖𝑓 Phone: ९८७६५४३२१०"
        indexed = normalize_with_offset_map(raw)
        self.assertEqual(indexed.normalized, "ID: Arif Phone: 9876543210")

        name_start = indexed.normalized.index("Arif")
        self.assertEqual(indexed.slice_original(name_start, name_start + 4), "𝐴𝑟𝑖𝑓")

        phone_start = indexed.normalized.index("9876543210")
        self.assertEqual(indexed.slice_original(phone_start, phone_start + 10), "९८७६५४३२१०")

    def test_combining_mark_expansion_prevents_splitting_devanagari_akshara(self) -> None:
        raw = "डॉ. रमेश"
        indexed = normalize_with_offset_map(raw)
        # Slice ending on 'म' (index 5) before matra 'े' (index 6) expands to include 'े'.
        orig_s, orig_e = indexed.to_original_span(4, 6)
        self.assertEqual(raw[orig_s:orig_e], "रमे")


class TransliterationTests(unittest.TestCase):
    def test_devanagari_names_and_conjuncts_transliterate_deterministically(self) -> None:
        self.assertEqual(transliterate_devanagari("रमेश"), "ramesh")
        self.assertEqual(transliterate_devanagari("मीरा"), "meera")
        self.assertEqual(transliterate_devanagari("राजन"), "rajan")
        self.assertEqual(transliterate_devanagari("महेश"), "mahesh")
        self.assertEqual(transliterate_devanagari("सुरेश"), "suresh")
        self.assertEqual(transliterate_devanagari("रिया"), "riya")
        self.assertEqual(transliterate_devanagari("फ़िरोज़"), "firoz")
        self.assertIn("ksh", transliterate_devanagari("क्षत्रिय"))
        self.assertIn("gy", transliterate_devanagari("ज्ञान"))

    def test_transliteration_offset_map_slices_original_hindi_in_hinglish_note(self) -> None:
        raw = "मरीज: मोहम्मद आरिफ, BP 150/90"
        indexed = transliterate_with_map(raw)
        norm_lower = indexed.normalized.lower()
        target = "mohammad aariph"
        idx = norm_lower.index(target)
        orig_s, orig_e = indexed.to_original_span(idx, idx + len(target))
        self.assertEqual(raw[orig_s:orig_e], "मोहम्मद आरिफ")


class NameNormalizationTests(unittest.TestCase):
    def test_cross_script_and_spelling_variants_converge_to_same_name_key(self) -> None:
        variants = [
            "Mohammad Arif",
            "Mohd. Arif",
            "Md Arif",
            "मोहम्मद आरिफ",
            "Arif, Mohammad",
            "Mr. Mohd Arif",
        ]
        keys = {normalize_person_name(v).name_key for v in variants}
        self.assertEqual(len(keys), 1)
        self.assertEqual(next(iter(keys)), "ARF_MHMD")

    def test_honorifics_stripped_without_collapsing_distinct_surnames(self) -> None:
        ji = normalize_person_name("Arif ji")
        sahab = normalize_person_name("Arif sahab")
        self.assertEqual(ji.canonical_name, "arif")
        self.assertEqual(ji.name_key, sahab.name_key)

        ramesh_k = normalize_person_name("Ramesh Kumar")
        ramesh_s = normalize_person_name("Ramesh Sharma")
        self.assertNotEqual(ramesh_k.name_key, ramesh_s.name_key)

    def test_rare_and_hyphenated_names_keep_all_non_honorific_tokens(self) -> None:
        norm = normalize_person_name("Smt. Kshetrimayum Padmini-Devi")
        self.assertEqual(norm.canonical_name, "kshetrimayum padmini devi")
        self.assertEqual(len(norm.tokens), 3)

    def test_empty_or_punctuation_only_returns_empty_name(self) -> None:
        empty = normalize_person_name("  ---  ")
        self.assertEqual(empty.canonical_name, "")
        self.assertEqual(empty.name_key, "")


class PhoneNormalizationTests(unittest.TestCase):
    def test_indian_mobile_formats_canonicalize_to_e164(self) -> None:
        variants = [
            "+91 98765-43210",
            "09876543210",
            "919876543210",
            "+91 (0) 98765 43210",
            "९८७६५४३२१०",
        ]
        for raw in variants:
            parsed = normalize_phone(raw)
            self.assertIsNotNone(parsed, msg=f"Failed to parse phone variant #{variants.index(raw)}")
            assert parsed is not None
            self.assertEqual(parsed.e164, "+919876543210")
            self.assertTrue(parsed.is_mobile)

    def test_landline_and_pin_date_guards(self) -> None:
        landline = normalize_phone("(022) 24567890")
        self.assertIsNotNone(landline)
        assert landline is not None
        self.assertEqual(landline.e164, "+912224567890")
        self.assertFalse(landline.is_mobile)

        self.assertIsNone(normalize_phone("411 045"))       # PIN code
        self.assertIsNone(normalize_phone("2024-05-12"))    # ISO date
        self.assertIsNone(normalize_phone("98765"))         # Too short
        self.assertIsNone(normalize_phone("1234567890123456"))  # Too long


class DateNormalizationTests(unittest.TestCase):
    def test_multilingual_indian_and_iso_dates_normalize_consistently(self) -> None:
        variants = [
            "1985-04-12",
            "12/04/1985",
            "12-04-1985",
            "12 Apr 1985",
            "12 अप्रैल 1985",
            "१२/०४/१९८५",
            "1985-04-12T08:30:00Z",
        ]
        for raw in variants:
            parsed = normalize_date(raw)
            self.assertIsNotNone(parsed)
            assert parsed is not None
            self.assertEqual(parsed.iso_date, "1985-04-12")
            self.assertEqual(parsed.year, "1985")

    def test_clinical_dosages_vitals_and_invalid_dates_are_rejected(self) -> None:
        self.assertIsNone(normalize_date("1-0-1"))
        self.assertIsNone(normalize_date("0-1-1"))
        self.assertIsNone(normalize_date("150/90"))
        self.assertIsNone(normalize_date("31/02/1990"))


if __name__ == "__main__":
    unittest.main()
