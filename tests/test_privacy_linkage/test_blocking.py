"""Synthetic tests for deterministic linkage blocking."""

from __future__ import annotations

import unittest

from src.contracts import PatientRecord
from src.linkage.blocking import (
    CandidatePair,
    combine_exact_attribute_blocks,
    evaluate_candidate_generation,
    exact_attribute_pairs,
    exact_name_dob_pairs,
    normalized_name_birth_year_pairs,
    relative_geography_pairs,
    typed_identifier_pairs,
)


def _record(
    record_ref: str,
    *,
    names: list[str],
    phones: list[str],
    ids: list[str] | None = None,
    dobs: list[str] | None = None,
    name_keys: list[str] | None = None,
    birth_years: list[str] | None = None,
    relative_name_keys: list[str] | None = None,
    geo_keys: list[str] | None = None,
) -> PatientRecord:
    """Build a minimal synthetic record using the shared contract."""

    return PatientRecord(
        record_ref=record_ref,
        source_ref=f"source_{record_ref}",
        loc="row:0",
        original_structure={},
        extracted_patient_attributes={
            "names": names,
            "phones": phones,
            "ids": ids or [],
            "dobs": dobs or [],
            "name_keys": name_keys or [],
            "birth_years": birth_years or [],
            "relative_name_keys": relative_name_keys or [],
            "geo_keys": geo_keys or [],
        },
    )


class ExactPhoneBlockingTests(unittest.TestCase):
    def test_cross_script_records_with_same_phone_become_candidates(self) -> None:
        records = [
            _record(
                "rec_1",
                names=["mohammad arif"],
                phones=["919876543210"],
            ),
            _record(
                "rec_2",
                names=["मोहम्मद आरिफ"],
                phones=["919876543210"],
            ),
            _record(
                "rec_3",
                names=["mohammad arif"],
                phones=["919999999999"],
            ),
        ]

        pairs = exact_attribute_pairs(records, "phones")

        self.assertEqual(
            pairs,
            [CandidatePair("rec_1", "rec_2", ("EXACT_PHONES",))],
        )

    def test_missing_phones_do_not_create_candidate_pairs(self) -> None:
        records = [
            _record("rec_1", names=["asha devi"], phones=[]),
            _record("rec_2", names=["asha devi"], phones=[""]),
            _record("rec_3", names=["asha devi"], phones=["   "]),
        ]

        pairs = exact_attribute_pairs(records, "phones")

        self.assertEqual(pairs, [])


class ExactIdentifierBlockingTests(unittest.TestCase):
    def test_same_health_id_becomes_candidate_despite_different_name_script(self) -> None:
        records = [
            _record(
                "rec_1",
                names=["ravi kumar"],
                phones=[],
                ids=["ABHA|0001"],
            ),
            _record(
                "rec_2",
                names=["रवि कुमार"],
                phones=[],
                ids=["ABHA|0001"],
            ),
            _record(
                "rec_3",
                names=["ravi kumar"],
                phones=[],
                ids=["ABHA|9999"],
            ),
        ]

        pairs = typed_identifier_pairs(records)

        self.assertEqual(
            pairs,
            [CandidatePair("rec_1", "rec_2", ("EXACT_ID_ABHA",))],
        )

    def test_same_local_id_from_different_hospitals_does_not_pair(self) -> None:
        records = [
            _record(
                "rec_1",
                names=["patient one"],
                phones=[],
                ids=["UHID|HOSPITAL_A|42"],
            ),
            _record(
                "rec_2",
                names=["patient two"],
                phones=[],
                ids=["UHID|HOSPITAL_B|42"],
            ),
        ]

        self.assertEqual(typed_identifier_pairs(records), [])


class ExactNameDobBlockingTests(unittest.TestCase):
    def test_name_requires_same_full_dob(self) -> None:
        records = [
            _record(
                "rec_1",
                names=["mohammad arif"],
                phones=[],
                dobs=["1979-04-12"],
            ),
            _record(
                "rec_2",
                names=["mohammad arif"],
                phones=[],
                dobs=["1979-04-12"],
            ),
            _record(
                "rec_3",
                names=["mohammad arif"],
                phones=[],
                dobs=["1980-04-12"],
            ),
            _record(
                "rec_4",
                names=["mohammad arif"],
                phones=[],
                dobs=[],
            ),
        ]

        self.assertEqual(
            exact_name_dob_pairs(records),
            [CandidatePair("rec_1", "rec_2", ("EXACT_NAME_DOB",))],
        )


class CrossScriptNameBlockingTests(unittest.TestCase):
    def test_name_key_also_requires_compatible_birth_year(self) -> None:
        records = [
            _record(
                "rec_1",
                names=["mohammad arif"],
                phones=[],
                name_keys=["mohammad-arif"],
                birth_years=["1979"],
            ),
            _record(
                "rec_2",
                names=["मोहम्मद आरिफ"],
                phones=[],
                name_keys=["mohammad-arif"],
                birth_years=["1979"],
            ),
            _record(
                "rec_3",
                names=["md arif"],
                phones=[],
                name_keys=["mohammad-arif"],
                birth_years=["1982"],
            ),
        ]

        self.assertEqual(
            normalized_name_birth_year_pairs(records),
            [CandidatePair("rec_1", "rec_2", ("NAME_KEY_BIRTH_YEAR",))],
        )


class RelativeGeographyBlockingTests(unittest.TestCase):
    def test_relative_name_requires_same_geography(self) -> None:
        records = [
            _record(
                "rec_1",
                names=["meera"],
                phones=[],
                relative_name_keys=["rajan"],
                geo_keys=["district-jaipur"],
            ),
            _record(
                "rec_2",
                names=["मीरा"],
                phones=[],
                relative_name_keys=["rajan"],
                geo_keys=["district-jaipur"],
            ),
            _record(
                "rec_3",
                names=["another meera"],
                phones=[],
                relative_name_keys=["rajan"],
                geo_keys=["district-udaipur"],
            ),
        ]

        self.assertEqual(
            relative_geography_pairs(records),
            [CandidatePair("rec_1", "rec_2", ("RELATIVE_GEO_KEY",))],
        )


class BlockingSafetyAndMetricsTests(unittest.TestCase):
    def test_oversized_common_bucket_is_skipped(self) -> None:
        records = [
            _record(
                f"rec_{index}",
                names=[f"patient {index}"],
                phones=["910000000000"],
            )
            for index in range(1, 6)
        ]

        self.assertEqual(
            exact_attribute_pairs(records, "phones", max_bucket_size=3),
            [],
        )

    def test_candidate_recall_reduction_time_and_memory_are_measured(self) -> None:
        records = [
            _record("rec_1", names=["patient one"], phones=["911111111111"]),
            _record("rec_2", names=["patient one"], phones=["911111111111"]),
            _record(
                "rec_3",
                names=["patient three"],
                phones=[],
                dobs=["1980-01-01"],
            ),
            _record(
                "rec_4",
                names=["patient three"],
                phones=[],
                dobs=["1980-01-01"],
            ),
            _record("rec_5", names=["patient five"], phones=["915555555555"]),
            _record("rec_6", names=["patient six"], phones=["916666666666"]),
        ]

        candidates, metrics = evaluate_candidate_generation(
            records,
            true_match_pairs={("rec_1", "rec_2"), ("rec_3", "rec_4")},
        )

        self.assertEqual(len(candidates), 2)
        self.assertEqual(metrics.total_possible_pairs, 15)
        self.assertEqual(metrics.candidate_pairs, 2)
        self.assertEqual(metrics.true_matches_recalled, 2)
        self.assertEqual(metrics.candidate_recall, 1.0)
        self.assertAlmostEqual(metrics.reduction_ratio, 13 / 15)
        self.assertGreaterEqual(metrics.elapsed_seconds, 0.0)
        self.assertGreater(metrics.peak_memory_bytes, 0)


class CombinedBlockingTests(unittest.TestCase):
    def test_phone_and_id_blocks_merge_duplicate_candidate_pair(self) -> None:
        records = [
            _record(
                "rec_1",
                names=["meera shah"],
                phones=["919876543210"],
                ids=["ABHA|0001"],
            ),
            _record(
                "rec_2",
                names=["मीरा शाह"],
                phones=["919876543210"],
                ids=["ABHA|0001"],
            ),
        ]

        pairs = combine_exact_attribute_blocks(records, ("phones", "ids"))

        self.assertEqual(
            pairs,
            [
                CandidatePair(
                    "rec_1",
                    "rec_2",
                    ("EXACT_ID_ABHA", "EXACT_PHONES"),
                )
            ],
        )

    def test_candidate_pairs_do_not_depend_on_input_order(self) -> None:
        records = [
            _record(
                "rec_1",
                names=["meera shah"],
                phones=["919876543210"],
                ids=["ABHA|0001"],
            ),
            _record(
                "rec_2",
                names=["मीरा शाह"],
                phones=["919876543210"],
                ids=["ABHA|0002"],
            ),
            _record(
                "rec_3",
                names=["m shah"],
                phones=["919999999999"],
                ids=["ABHA|0001"],
            ),
        ]

        forward = combine_exact_attribute_blocks(records, ("phones", "ids"))
        reversed_input = combine_exact_attribute_blocks(
            list(reversed(records)), ("phones", "ids")
        )

        self.assertEqual(forward, reversed_input)

    def test_repeated_values_create_no_self_pairs_or_duplicate_pairs(self) -> None:
        repeated_record = _record(
            "rec_1",
            names=["asha devi"],
            phones=["919876543210", "919876543210"],
            ids=["ABHA|0001", "ABHA|0001"],
        )

        self.assertEqual(
            combine_exact_attribute_blocks(
                [repeated_record], ("phones", "ids")
            ),
            [],
        )

        second_record = _record(
            "rec_2",
            names=["आशा देवी"],
            phones=["919876543210"],
            ids=["ABHA|0001"],
        )

        self.assertEqual(
            combine_exact_attribute_blocks(
                [repeated_record, second_record], ("phones", "ids")
            ),
            [
                CandidatePair(
                    "rec_1",
                    "rec_2",
                    ("EXACT_ID_ABHA", "EXACT_PHONES"),
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
