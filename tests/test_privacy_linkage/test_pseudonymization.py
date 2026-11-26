"""Synthetic tests for stable HMAC patient pseudonyms."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import unittest

from src.contracts import (
    DetectionSpan,
    PatientCluster,
    PatientRecord,
    ResolutionStatus,
    SpanRole,
    TransformType,
)
from src.privacy.pseudonymization import (
    DEFAULT_PSEUDONYM_BYTES,
    HMACPseudonymizer,
    PSEUDONYM_DOMAIN,
    assign_cluster_pseudonyms,
)


def _record(
    record_ref: str,
    *,
    ids: list[str] | None = None,
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
            "ids": ids or [],
            "phones": phones or [],
            "dobs": dobs or [],
            "name_keys": name_keys or [],
            "birth_years": birth_years or [],
            "relative_name_keys": relative_name_keys or [],
            "geo_keys": geo_keys or [],
        },
    )


def _cluster(
    cluster_ref: str,
    *member_record_refs: str,
    status: ResolutionStatus = ResolutionStatus.RESOLVED,
) -> PatientCluster:
    return PatientCluster(
        cluster_ref=cluster_ref,
        member_record_refs=tuple(member_record_refs),
        resolution_status=status,
    )


class HMACPseudonymAssignmentTests(unittest.TestCase):
    def test_all_records_in_cluster_receive_same_pseudonym(self) -> None:
        records = [
            _record("rec_1", ids=["ABHA|0001"]),
            _record("rec_2", ids=["ABHA|0001"]),
        ]
        cluster = _cluster("clu_1", "rec_1", "rec_2")

        metrics = assign_cluster_pseudonyms(records, [cluster], b"secret-alpha")

        self.assertTrue(cluster.pseudonym_id.startswith("PSN-"))
        self.assertEqual(records[0].pseudonym_id, cluster.pseudonym_id)
        self.assertEqual(records[1].pseudonym_id, cluster.pseudonym_id)
        self.assertEqual(metrics.assigned_clusters, 1)
        self.assertEqual(metrics.unique_pseudonyms, 1)

    def test_hmac_output_matches_versioned_domain_separated_input(self) -> None:
        record = _record("rec_1", ids=["ABHA|0001"])
        cluster = _cluster("clu_1", "rec_1")
        secret = b"secret-alpha"

        assign_cluster_pseudonyms([record], [cluster], secret)

        payload = json.dumps(
            ["raksha-identity-v1", "global-id", "ABHA", "0001"],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hmac.new(secret, PSEUDONYM_DOMAIN + payload, hashlib.sha256).digest()
        encoded = (
            base64.b32encode(digest[:DEFAULT_PSEUDONYM_BYTES])
            .decode("ascii")
            .rstrip("=")
        )
        self.assertEqual(cluster.pseudonym_id, f"PSN-{encoded}")

    def test_same_identity_and_secret_are_deterministic_across_order(self) -> None:
        forward_records = [
            _record("rec_1", ids=["ABHA|0001"], phones=["911111111111"]),
            _record("rec_2", ids=["ABHA|0001"], phones=["922222222222"]),
        ]
        reverse_records = list(
            reversed(
                [
                    _record("rec_1", ids=["ABHA|0001"], phones=["911111111111"]),
                    _record("rec_2", ids=["ABHA|0001"], phones=["922222222222"]),
                ]
            )
        )
        forward_cluster = _cluster("clu_1", "rec_1", "rec_2")
        reverse_cluster = _cluster("clu_1", "rec_2", "rec_1")

        assign_cluster_pseudonyms(
            forward_records, [forward_cluster], b"secret-alpha"
        )
        assign_cluster_pseudonyms(
            reverse_records, [reverse_cluster], b"secret-alpha"
        )

        self.assertEqual(forward_cluster.pseudonym_id, reverse_cluster.pseudonym_id)

    def test_different_secret_changes_pseudonym(self) -> None:
        record_a = _record("rec_1", ids=["ABHA|0001"])
        record_b = _record("rec_1", ids=["ABHA|0001"])
        cluster_a = _cluster("clu_1", "rec_1")
        cluster_b = _cluster("clu_1", "rec_1")

        assign_cluster_pseudonyms([record_a], [cluster_a], b"secret-alpha")
        assign_cluster_pseudonyms([record_b], [cluster_b], b"secret-beta")

        self.assertNotEqual(cluster_a.pseudonym_id, cluster_b.pseudonym_id)

    def test_different_identities_receive_different_pseudonyms(self) -> None:
        records = [
            _record("rec_1", ids=["ABHA|0001"]),
            _record("rec_2", ids=["ABHA|0002"]),
        ]
        clusters = [_cluster("clu_1", "rec_1"), _cluster("clu_2", "rec_2")]

        metrics = assign_cluster_pseudonyms(records, clusters, b"secret-alpha")

        self.assertNotEqual(clusters[0].pseudonym_id, clusters[1].pseudonym_id)
        self.assertEqual(metrics.unique_pseudonyms, 2)


class PseudonymSafetyTests(unittest.TestCase):
    def test_unresolved_cluster_receives_no_pseudonym(self) -> None:
        record = _record("rec_1")
        cluster = _cluster(
            "clu_1", "rec_1", status=ResolutionStatus.UNRESOLVED
        )

        metrics = assign_cluster_pseudonyms([record], [cluster], b"secret-alpha")

        self.assertIsNone(cluster.pseudonym_id)
        self.assertIsNone(record.pseudonym_id)
        self.assertEqual(metrics.unresolved_clusters, 1)

    def test_conflicting_identity_downgrades_cluster_without_token(self) -> None:
        records = [
            _record("rec_1", ids=["ABHA|0001"]),
            _record("rec_2", ids=["ABHA|9999"]),
        ]
        cluster = _cluster("clu_1", "rec_1", "rec_2")

        metrics = assign_cluster_pseudonyms(records, [cluster], b"secret-alpha")

        self.assertEqual(cluster.resolution_status, ResolutionStatus.CONFLICT)
        self.assertIsNone(cluster.pseudonym_id)
        self.assertEqual(metrics.conflict_clusters, 1)

    def test_weak_resolved_cluster_is_downgraded_to_unresolved(self) -> None:
        record = _record("rec_1", name_keys=["ravi"])
        cluster = _cluster("clu_1", "rec_1")

        assign_cluster_pseudonyms([record], [cluster], b"secret-alpha")

        self.assertEqual(cluster.resolution_status, ResolutionStatus.UNRESOLVED)
        self.assertIsNone(cluster.pseudonym_id)

    def test_empty_secret_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty secret key"):
            assign_cluster_pseudonyms(
                [_record("rec_1", ids=["ABHA|0001"])],
                [_cluster("clu_1", "rec_1")],
                b"",
            )

    def test_truncated_collision_is_extended_deterministically(self) -> None:
        secret = b"collision-test-secret"
        first_byte_to_value: dict[int, str] = {}
        collision_values: tuple[str, str] | None = None
        for number in range(1000):
            value = f"{number:04d}"
            payload = json.dumps(
                ["raksha-identity-v1", "global-id", "ABHA", value],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            first_byte = hmac.new(
                secret, PSEUDONYM_DOMAIN + payload, hashlib.sha256
            ).digest()[0]
            if first_byte in first_byte_to_value:
                collision_values = (first_byte_to_value[first_byte], value)
                break
            first_byte_to_value[first_byte] = value

        self.assertIsNotNone(collision_values)
        value_a, value_b = collision_values or ("", "")
        records = [
            _record("rec_1", ids=[f"ABHA|{value_a}"]),
            _record("rec_2", ids=[f"ABHA|{value_b}"]),
        ]
        clusters = [_cluster("clu_1", "rec_1"), _cluster("clu_2", "rec_2")]

        metrics = assign_cluster_pseudonyms(
            records,
            clusters,
            secret,
            initial_digest_bytes=1,
        )

        self.assertNotEqual(clusters[0].pseudonym_id, clusters[1].pseudonym_id)
        self.assertGreater(metrics.collision_extensions, 0)


class PrivacyDecisionIntegrationTests(unittest.TestCase):
    def test_direct_patient_identifiers_receive_pseudonym_decisions(self) -> None:
        record = _record("rec_1", ids=["ABHA|0001"])
        record.detections = [
            DetectionSpan(
                record_ref="rec_1",
                field_path="col:0",
                start=0,
                end=10,
                category="PATIENT_NAME",
                role=SpanRole.DIRECT_PII,
                confidence=1.0,
                detector_source="synthetic",
            ),
            DetectionSpan(
                record_ref="rec_1",
                field_path="col:1",
                start=0,
                end=12,
                category="PHONE",
                role=SpanRole.DIRECT_PII,
                confidence=1.0,
                detector_source="synthetic",
            ),
            DetectionSpan(
                record_ref="rec_1",
                field_path="col:2",
                start=0,
                end=5,
                category="PATIENT_NAME",
                role=SpanRole.CLINICAL_PROTECTED,
                confidence=1.0,
                detector_source="synthetic",
            ),
        ]
        cluster = _cluster("clu_1", "rec_1")

        decisions = HMACPseudonymizer().transform(
            [record], [cluster], b"secret-alpha"
        )

        self.assertEqual(len(decisions), 2)
        self.assertTrue(all(d.transform_type == TransformType.PSEUDONYMIZE for d in decisions))
        self.assertTrue(all(d.replacement_value == record.pseudonym_id for d in decisions))
        self.assertEqual({d.field_path for d in decisions}, {"col:0", "col:1"})
        self.assertNotIn("0001", repr(decisions))


if __name__ == "__main__":
    unittest.main()
