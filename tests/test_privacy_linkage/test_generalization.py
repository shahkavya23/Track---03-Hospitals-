"""Tests for adaptive quasi-identifier generalization."""

from __future__ import annotations

import unittest

from src.contracts import DetectionSpan, FieldNode, PatientRecord, SpanRole
from src.privacy.generalization import (
    AdaptiveGeneralizer,
    age_band,
    equivalence_class_sizes,
    generalize_pin,
)


def _record(
    record_ref: str,
    *,
    age: str,
    pin: str,
    village: str,
    profile_geo: str,
    diagnosis: str = "dengue",
) -> PatientRecord:
    record = PatientRecord(
        record_ref=record_ref,
        source_ref=f"source_{record_ref}",
        loc="row:0",
        original_structure={},
        fields=[
            FieldNode("age", age, "age", False),
            FieldNode("pin", pin, "pin", False),
            FieldNode("village", village, "village", False),
            FieldNode("diagnosis", diagnosis, "diagnosis", False),
        ],
        extracted_patient_attributes={
            "ages": [age],
            "genders": ["F"],
            "geo_keys": [profile_geo],
            "diagnoses": [diagnosis],
            "visit_years": ["2026"],
            "districts": ["Jaipur District"],
            "states": ["Rajasthan"],
        },
    )
    record.detections = [
        DetectionSpan(record_ref, "age", 0, len(age), "AGE", SpanRole.QUASI_IDENTIFIER, 1.0, "synthetic"),
        DetectionSpan(record_ref, "pin", 0, len(pin), "PIN_CODE", SpanRole.QUASI_IDENTIFIER, 1.0, "synthetic"),
        DetectionSpan(record_ref, "village", 0, len(village), "VILLAGE", SpanRole.QUASI_IDENTIFIER, 1.0, "synthetic"),
        DetectionSpan(record_ref, "diagnosis", 0, len(diagnosis), "DIAGNOSIS", SpanRole.CLINICAL_PROTECTED, 1.0, "synthetic"),
    ]
    return record


class GeneralizationPrimitiveTests(unittest.TestCase):
    def test_age_band_contains_true_age(self) -> None:
        self.assertEqual(age_band(47, 5), "45-49")
        self.assertEqual(age_band(47, 10), "40-49")
        self.assertEqual(age_band(92, 10), "90+")

    def test_pin_generalization_preserves_only_prefix(self) -> None:
        self.assertEqual(generalize_pin("302001", 3), "302XXX")
        self.assertEqual(generalize_pin("302001", 2), "30XXXX")


class AdaptiveGeneralizationTests(unittest.TestCase):
    def test_equivalence_sizes_are_measured_from_profiles(self) -> None:
        records = [
            _record("rec_1", age="47", pin="302001", village="A", profile_geo="A"),
            _record("rec_2", age="47", pin="302001", village="A", profile_geo="A"),
            _record("rec_3", age="52", pin="302002", village="B", profile_geo="B"),
        ]

        self.assertEqual(
            equivalence_class_sizes(records),
            {"rec_1": 2, "rec_2": 2, "rec_3": 1},
        )

    def test_moderate_risk_uses_five_year_age_and_district(self) -> None:
        records = [
            _record("rec_1", age="47", pin="302001", village="A", profile_geo="A"),
            _record("rec_2", age="47", pin="302001", village="A", profile_geo="A"),
        ]

        decisions = AdaptiveGeneralizer().transform(records)
        replacements = {
            (item.record_ref, item.field_path): item.replacement_value
            for item in decisions
        }

        self.assertEqual(replacements[("rec_1", "age")], "45-49")
        self.assertEqual(replacements[("rec_1", "pin")], "302XXX")
        self.assertEqual(replacements[("rec_1", "village")], "Jaipur District")
        self.assertNotIn(("rec_1", "diagnosis"), replacements)

    def test_high_risk_uses_wider_age_pin_and_state(self) -> None:
        record = _record(
            "rec_1", age="47", pin="302001", village="Tiny Village", profile_geo="tiny"
        )
        generalizer = AdaptiveGeneralizer()

        decisions = generalizer.transform([record])
        replacements = {item.field_path: item.replacement_value for item in decisions}

        self.assertEqual(replacements["age"], "40-49")
        self.assertEqual(replacements["pin"], "30XXXX")
        self.assertEqual(replacements["village"], "Rajasthan")
        self.assertEqual(generalizer.last_metrics.high_risk_records, 1)

    def test_low_risk_group_needs_no_additional_generalization(self) -> None:
        records = [
            _record(f"rec_{index}", age="47", pin="302001", village="A", profile_geo="A")
            for index in range(3)
        ]

        decisions = AdaptiveGeneralizer().transform(records)

        self.assertEqual(decisions, [])


if __name__ == "__main__":
    unittest.main()
