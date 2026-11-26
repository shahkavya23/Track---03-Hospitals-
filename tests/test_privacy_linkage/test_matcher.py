"""Synthetic tests for conservative pairwise matching."""

from __future__ import annotations

import unittest

from src.contracts import LinkageDecision, LinkageVerdict, PatientRecord
from src.linkage.blocking import CandidatePair
from src.linkage.matcher import (
    MatcherPolicy,
    evaluate_matching,
    match_candidates,
    match_pair,
)


def _record(
    record_ref: str,
    *,
    ids: list[str],
    names: list[str] | None = None,
    phones: list[str] | None = None,
    dobs: list[str] | None = None,
    name_keys: list[str] | None = None,
    birth_years: list[str] | None = None,
    relative_name_keys: list[str] | None = None,
    geo_keys: list[str] | None = None,
) -> PatientRecord:
    return PatientRecord(
        record_ref=record_ref,
        source_ref=f"source_{record_ref}",
        loc="row:0",
        original_structure={},
        extracted_patient_attributes={
            "ids": ids,
            "names": names or [],
            "phones": phones or [],
            "dobs": dobs or [],
            "name_keys": name_keys or [],
            "birth_years": birth_years or [],
            "relative_name_keys": relative_name_keys or [],
            "geo_keys": geo_keys or [],
        },
    )


class StrongIdentifierMatchingTests(unittest.TestCase):
    def test_same_global_health_id_is_a_match(self) -> None:
        left = _record("rec_2", ids=["ABHA|0001"])
        right = _record("rec_1", ids=["ABHA|0001"])

        decision = match_pair(left, right)

        self.assertEqual(
            decision,
            LinkageDecision(
                record_ref_a="rec_1",
                record_ref_b="rec_2",
                decision=LinkageVerdict.MATCH,
                score=1.0,
                evidence_categories=("EXACT_ID_ABHA",),
            ),
        )

    def test_different_global_health_ids_are_a_non_match(self) -> None:
        left = _record("rec_1", ids=["ABHA|0001"])
        right = _record("rec_2", ids=["ABHA|9999"])

        decision = match_pair(left, right)

        self.assertEqual(
            decision,
            LinkageDecision(
                record_ref_a="rec_1",
                record_ref_b="rec_2",
                decision=LinkageVerdict.NON_MATCH,
                score=-1.0,
                evidence_categories=("CONFLICT_ID_ABHA",),
            ),
        )

    def test_global_id_conflict_overrides_all_supporting_matches(self) -> None:
        shared = {
            "names": ["meera"],
            "phones": ["919876543210"],
            "dobs": ["1985-01-02"],
            "name_keys": ["meera"],
            "birth_years": ["1985"],
            "relative_name_keys": ["rajan"],
            "geo_keys": ["district-jaipur"],
        }
        left = _record("rec_1", ids=["ABHA|0001"], **shared)
        right = _record("rec_2", ids=["ABHA|9999"], **shared)

        decision = match_pair(left, right)

        self.assertEqual(decision.decision, LinkageVerdict.NON_MATCH)
        self.assertEqual(decision.score, -1.0)
        self.assertEqual(decision.evidence_categories, ("CONFLICT_ID_ABHA",))

    def test_multiple_values_for_one_global_id_type_abstain(self) -> None:
        left = _record("rec_1", ids=["ABHA|0001", "ABHA|0002"])
        right = _record("rec_2", ids=["ABHA|0001"])

        decision = match_pair(left, right)

        self.assertEqual(decision.decision, LinkageVerdict.ABSTAIN)
        self.assertEqual(decision.evidence_categories, ("AMBIGUOUS_ID_ABHA",))

    def test_malformed_identifier_is_ignored_safely(self) -> None:
        left = _record("rec_1", ids=["ABHA", "|", "ABHA|"])
        right = _record("rec_2", ids=["ABHA", "|", "ABHA|"])

        decision = match_pair(left, right)

        self.assertEqual(decision.decision, LinkageVerdict.ABSTAIN)
        self.assertNotIn("ABHA|", repr(decision))

    def test_matching_global_id_with_conflicting_dob_abstains(self) -> None:
        left = _record("rec_1", ids=["ABHA|0001"], dobs=["1985-01-02"])
        right = _record("rec_2", ids=["ABHA|0001"], dobs=["1990-03-04"])

        decision = match_pair(left, right)

        self.assertEqual(decision.decision, LinkageVerdict.ABSTAIN)
        self.assertEqual(
            decision.evidence_categories,
            ("CONFLICT_DOB", "EXACT_ID_ABHA"),
        )


class LocalIdentifierMatchingTests(unittest.TestCase):
    def test_same_local_id_and_dob_are_a_match(self) -> None:
        left = _record(
            "rec_1", ids=["UHID|HOSPITAL_A|42"], dobs=["1985-01-02"]
        )
        right = _record(
            "rec_2", ids=["UHID|HOSPITAL_A|42"], dobs=["1985-01-02"]
        )

        decision = match_pair(left, right)

        self.assertEqual(decision.decision, LinkageVerdict.MATCH)
        self.assertEqual(decision.score, 1.0)
        self.assertEqual(
            decision.evidence_categories,
            ("EXACT_DOB", "EXACT_ID_UHID"),
        )

    def test_same_local_number_from_different_issuers_abstains(self) -> None:
        left = _record("rec_1", ids=["UHID|HOSPITAL_A|42"])
        right = _record("rec_2", ids=["UHID|HOSPITAL_B|42"])

        self.assertEqual(match_pair(left, right).decision, LinkageVerdict.ABSTAIN)

    def test_different_local_ids_in_same_namespace_are_a_non_match(self) -> None:
        left = _record("rec_1", ids=["MRN|HOSPITAL_A|42"])
        right = _record("rec_2", ids=["MRN|HOSPITAL_A|99"])

        decision = match_pair(left, right)

        self.assertEqual(decision.decision, LinkageVerdict.NON_MATCH)
        self.assertEqual(decision.evidence_categories, ("CONFLICT_ID_MRN",))


class WeakEvidenceMatchingTests(unittest.TestCase):
    def test_same_name_without_supporting_evidence_abstains(self) -> None:
        left = _record("rec_1", ids=[], names=["ravi kumar"])
        right = _record("rec_2", ids=[], names=["ravi kumar"])

        decision = match_pair(left, right)

        self.assertEqual(
            decision,
            LinkageDecision(
                record_ref_a="rec_1",
                record_ref_b="rec_2",
                decision=LinkageVerdict.ABSTAIN,
                score=0.0,
                evidence_categories=(),
            ),
        )


class SupportingEvidenceMatchingTests(unittest.TestCase):
    def test_exact_phone_and_dob_are_a_match(self) -> None:
        left = _record(
            "rec_1",
            ids=[],
            names=["mohammad arif"],
            phones=["919876543210"],
            dobs=["1979-04-12"],
        )
        right = _record(
            "rec_2",
            ids=[],
            names=["मोहम्मद आरिफ"],
            phones=["919876543210"],
            dobs=["1979-04-12"],
        )

        decision = match_pair(left, right)

        self.assertEqual(
            decision,
            LinkageDecision(
                record_ref_a="rec_1",
                record_ref_b="rec_2",
                decision=LinkageVerdict.MATCH,
                score=0.9,
                evidence_categories=("EXACT_DOB", "EXACT_PHONE"),
            ),
        )

    def test_same_phone_with_conflicting_dob_is_a_non_match(self) -> None:
        left = _record(
            "rec_1",
            ids=[],
            names=["ravi kumar"],
            phones=["919876543210"],
            dobs=["1979-04-12"],
        )
        right = _record(
            "rec_2",
            ids=[],
            names=["ravi kumar"],
            phones=["919876543210"],
            dobs=["1988-09-03"],
        )

        decision = match_pair(left, right)

        self.assertEqual(
            decision,
            LinkageDecision(
                record_ref_a="rec_1",
                record_ref_b="rec_2",
                decision=LinkageVerdict.NON_MATCH,
                score=-0.8,
                evidence_categories=("CONFLICT_DOB", "EXACT_PHONE"),
            ),
        )

    def test_same_phone_with_missing_dob_abstains(self) -> None:
        left = _record(
            "rec_1",
            ids=[],
            names=["asha devi"],
            phones=["919876543210"],
            dobs=["1979-04-12"],
        )
        right = _record(
            "rec_2",
            ids=[],
            names=["आशा देवी"],
            phones=["919876543210"],
            dobs=[],
        )

        decision = match_pair(left, right)

        self.assertEqual(
            decision,
            LinkageDecision(
                record_ref_a="rec_1",
                record_ref_b="rec_2",
                decision=LinkageVerdict.ABSTAIN,
                score=0.4,
                evidence_categories=("EXACT_PHONE",),
            ),
        )

    def test_four_compatible_supporting_signals_are_a_match(self) -> None:
        left = _record(
            "rec_1",
            ids=[],
            names=["meera"],
            name_keys=["meera"],
            birth_years=["1985"],
            relative_name_keys=["rajan"],
            geo_keys=["district-jaipur"],
        )
        right = _record(
            "rec_2",
            ids=[],
            names=["मीरा"],
            name_keys=["meera"],
            birth_years=["1985"],
            relative_name_keys=["rajan"],
            geo_keys=["district-jaipur"],
        )

        decision = match_pair(left, right)

        self.assertEqual(
            decision,
            LinkageDecision(
                record_ref_a="rec_1",
                record_ref_b="rec_2",
                decision=LinkageVerdict.MATCH,
                score=0.8,
                evidence_categories=(
                    "BIRTH_YEAR",
                    "GEO_KEY",
                    "NAME_KEY",
                    "RELATIVE_NAME_KEY",
                ),
            ),
        )

    def test_only_three_supporting_signals_abstain(self) -> None:
        left = _record(
            "rec_1",
            ids=[],
            names=["meera"],
            name_keys=["meera"],
            birth_years=["1985"],
            relative_name_keys=["rajan"],
            geo_keys=["district-jaipur"],
        )
        right = _record(
            "rec_2",
            ids=[],
            names=["मीरा"],
            name_keys=["meera"],
            birth_years=["1985"],
            relative_name_keys=["rajan"],
            geo_keys=[],
        )

        decision = match_pair(left, right)

        self.assertEqual(
            decision,
            LinkageDecision(
                record_ref_a="rec_1",
                record_ref_b="rec_2",
                decision=LinkageVerdict.ABSTAIN,
                score=0.6,
                evidence_categories=(
                    "BIRTH_YEAR",
                    "NAME_KEY",
                    "RELATIVE_NAME_KEY",
                ),
            ),
        )

    def test_fuzzy_name_needs_other_strong_support(self) -> None:
        left = _record(
            "rec_1",
            ids=[],
            name_keys=["mohammad-arif"],
            dobs=["1979-04-12"],
            geo_keys=["district-jaipur"],
        )
        right = _record(
            "rec_2",
            ids=[],
            name_keys=["mohamad-arif"],
            dobs=["1979-04-12"],
            geo_keys=["district-jaipur"],
        )

        decision = match_pair(left, right)

        self.assertEqual(decision.decision, LinkageVerdict.MATCH)
        self.assertEqual(decision.score, 0.9)
        self.assertEqual(
            decision.evidence_categories,
            ("EXACT_DOB", "FUZZY_NAME", "GEO_KEY"),
        )

    def test_fuzzy_name_alone_abstains(self) -> None:
        left = _record("rec_1", ids=[], name_keys=["mohammad-arif"])
        right = _record("rec_2", ids=[], name_keys=["mohamad-arif"])

        decision = match_pair(left, right)

        self.assertEqual(decision.decision, LinkageVerdict.ABSTAIN)
        self.assertEqual(decision.score, 0.2)
        self.assertEqual(decision.evidence_categories, ("FUZZY_NAME",))


class MatcherPolicyTests(unittest.TestCase):
    def test_higher_match_threshold_changes_match_to_abstain(self) -> None:
        left = _record(
            "rec_1", ids=[], phones=["919876543210"], dobs=["1979-04-12"]
        )
        right = _record(
            "rec_2", ids=[], phones=["919876543210"], dobs=["1979-04-12"]
        )

        decision = match_pair(left, right, MatcherPolicy(match_threshold=0.95))

        self.assertEqual(decision.decision, LinkageVerdict.ABSTAIN)
        self.assertEqual(decision.score, 0.9)

    def test_invalid_threshold_order_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MatcherPolicy(match_threshold=0.5, non_match_threshold=0.6)


class BatchMatchingAndMetricsTests(unittest.TestCase):
    def test_batch_matching_is_sorted_and_deduplicated(self) -> None:
        records = [
            _record("rec_1", ids=["ABHA|0001"]),
            _record("rec_2", ids=["ABHA|0001"]),
            _record("rec_3", ids=["ABHA|0003"]),
            _record("rec_4", ids=["ABHA|0004"]),
        ]
        candidates = [
            CandidatePair("rec_4", "rec_3", ("test",)),
            CandidatePair("rec_2", "rec_1", ("test",)),
            CandidatePair("rec_1", "rec_2", ("duplicate",)),
            CandidatePair("rec_1", "rec_1", ("self",)),
        ]

        decisions = match_candidates(records, candidates)

        self.assertEqual(
            [(item.record_ref_a, item.record_ref_b) for item in decisions],
            [("rec_1", "rec_2"), ("rec_3", "rec_4")],
        )
        self.assertEqual(decisions[0].decision, LinkageVerdict.MATCH)
        self.assertEqual(decisions[1].decision, LinkageVerdict.NON_MATCH)

    def test_matching_quality_and_resources_are_measured(self) -> None:
        records = [
            _record("rec_1", ids=["ABHA|0001"]),
            _record("rec_2", ids=["ABHA|0001"]),
            _record(
                "rec_3", ids=[], phones=["919111111111"], dobs=["1980-01-01"]
            ),
            _record(
                "rec_4", ids=[], phones=["919111111111"], dobs=["1980-01-01"]
            ),
            _record("rec_5", ids=["ABHA|0005"]),
            _record("rec_6", ids=["ABHA|0006"]),
            _record("rec_7", ids=[], names=["ravi kumar"]),
            _record("rec_8", ids=[], names=["ravi kumar"]),
        ]
        candidates = [
            CandidatePair("rec_1", "rec_2", ("test",)),
            CandidatePair("rec_3", "rec_4", ("test",)),
            CandidatePair("rec_5", "rec_6", ("test",)),
            CandidatePair("rec_7", "rec_8", ("test",)),
        ]

        _, metrics = evaluate_matching(
            records,
            candidates,
            true_match_pairs={("rec_1", "rec_2"), ("rec_3", "rec_4")},
        )

        self.assertEqual(metrics.decisions_total, 4)
        self.assertEqual(metrics.matches, 2)
        self.assertEqual(metrics.non_matches, 1)
        self.assertEqual(metrics.abstentions, 1)
        self.assertEqual(metrics.precision, 1.0)
        self.assertEqual(metrics.recall, 1.0)
        self.assertEqual(metrics.false_merge_rate, 0.0)
        self.assertEqual(metrics.abstention_rate, 0.25)
        self.assertGreaterEqual(metrics.elapsed_seconds, 0.0)
        self.assertGreater(metrics.peak_memory_bytes, 0)


if __name__ == "__main__":
    unittest.main()
