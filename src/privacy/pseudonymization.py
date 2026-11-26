"""Stable, secret-keyed patient pseudonym assignment."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
from typing import Sequence

from src.contracts import (
    PatientCluster,
    PatientRecord,
    PrivacyDecision,
    ResolutionStatus,
    SpanRole,
    TransformType,
)


PSEUDONYM_DOMAIN = b"raksha:v1:pseudonym\0"
GLOBAL_ID_PRIORITY = ("ABHA", "AADHAAR", "PAN")
LOCAL_ID_PRIORITY = ("UHID", "MRN", "INSURANCE")
DEFAULT_PSEUDONYM_BYTES = 13  # 104 bits before Base32 encoding
DEFAULT_PATIENT_CATEGORIES = frozenset(
    {
        # Direct identity-bearing values are replaced by the cluster token.
        # Staff/facility names are intentionally excluded: they are not patient
        # identity and must remain clinically useful context.
        "PATIENT_NAME",
        "PERSON_NAME",
    }
)


@dataclass(frozen=True, slots=True)
class PseudonymizationMetrics:
    """Safe aggregate measurements from pseudonym assignment."""

    clusters_total: int
    assigned_clusters: int
    unresolved_clusters: int
    conflict_clusters: int
    unique_pseudonyms: int
    collision_extensions: int


def _normalized_values(record: PatientRecord, attribute: str) -> set[str]:
    return {
        value.strip()
        for value in record.extracted_patient_attributes.get(attribute, [])
        if value.strip()
    }


def _identity_payload(
    cluster: PatientCluster,
    records_by_ref: dict[str, PatientRecord],
) -> tuple[ResolutionStatus, bytes | None]:
    """Select one deterministic, adequately strong cluster identity anchor."""

    global_ids: dict[str, set[str]] = {}
    local_ids: dict[tuple[str, str], set[str]] = {}
    phones: set[str] = set()
    dobs: set[str] = set()
    name_keys: set[str] = set()
    birth_years: set[str] = set()
    relative_name_keys: set[str] = set()
    geo_keys: set[str] = set()

    for record_ref in cluster.member_record_refs:
        record = records_by_ref[record_ref]
        phones.update(_normalized_values(record, "phones"))
        dobs.update(_normalized_values(record, "dobs"))
        name_keys.update(_normalized_values(record, "name_keys"))
        birth_years.update(_normalized_values(record, "birth_years"))
        relative_name_keys.update(_normalized_values(record, "relative_name_keys"))
        geo_keys.update(_normalized_values(record, "geo_keys"))

        for identifier in record.extracted_patient_attributes.get("ids", []):
            parts = [part.strip() for part in identifier.split("|")]
            if len(parts) == 2 and all(parts):
                identifier_type = parts[0].upper()
                if identifier_type in GLOBAL_ID_PRIORITY:
                    global_ids.setdefault(identifier_type, set()).add(parts[1])
            elif len(parts) == 3 and all(parts):
                identifier_type = parts[0].upper()
                if identifier_type in LOCAL_ID_PRIORITY:
                    namespace = (identifier_type, parts[1].upper())
                    local_ids.setdefault(namespace, set()).add(parts[2])

    if any(len(values) > 1 for values in global_ids.values()):
        return ResolutionStatus.CONFLICT, None
    if any(len(values) > 1 for values in local_ids.values()):
        return ResolutionStatus.CONFLICT, None

    payload: list[str] | None = None
    for identifier_type in GLOBAL_ID_PRIORITY:
        if identifier_type in global_ids:
            payload = [
                "raksha-identity-v1",
                "global-id",
                identifier_type,
                min(global_ids[identifier_type]),
            ]
            break

    if payload is None:
        for identifier_type in LOCAL_ID_PRIORITY:
            namespaces = sorted(
                namespace
                for namespace in local_ids
                if namespace[0] == identifier_type
            )
            if namespaces:
                namespace = namespaces[0]
                payload = [
                    "raksha-identity-v1",
                    "local-id",
                    namespace[0],
                    namespace[1],
                    min(local_ids[namespace]),
                ]
                break

    if payload is None and phones and dobs:
        payload = [
            "raksha-identity-v1",
            "phone-dob",
            min(phones),
            min(dobs),
        ]

    if (
        payload is None
        and name_keys
        and birth_years
        and relative_name_keys
        and geo_keys
    ):
        payload = [
            "raksha-identity-v1",
            "supported-demographics",
            min(name_keys),
            min(birth_years),
            min(relative_name_keys),
            min(geo_keys),
        ]

    # A multi-record cluster created from independent supporting evidence needs
    # a stable anchor even when no single government identifier is present.
    if payload is None and len(cluster.member_record_refs) > 1 and name_keys and phones and geo_keys:
        payload = [
            "raksha-identity-v1",
            "corroborated-cluster",
            min(name_keys),
            min(phones),
            min(geo_keys),
        ]

    # A non-ambiguous singleton is still a real patient.  Prefer its encounter
    # number as the stable anchor; otherwise use the deterministic record ref.
    if payload is None and len(cluster.member_record_refs) == 1:
        record = records_by_ref[cluster.member_record_refs[0]]
        encounter_values = sorted({
            field.raw_value.strip()
            for field in record.fields
            if field.raw_value.strip()
            and any(
                span.field_path == field.field_path and span.category.upper() == "CASE_NO"
                for span in record.detections
            )
        })
        payload = [
            "raksha-identity-v1",
            "singleton-record",
            encounter_values[0] if encounter_values else hashlib.sha256(json.dumps(
                record.original_structure, ensure_ascii=False, sort_keys=True,
                separators=(',', ':')).encode()).hexdigest(),
        ]

    if payload is None:
        return ResolutionStatus.UNRESOLVED, None
    canonical = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return ResolutionStatus.RESOLVED, canonical


def _token(digest: bytes, digest_bytes: int) -> str:
    encoded = base64.b32encode(digest[:digest_bytes]).decode("ascii").rstrip("=")
    return f"PSN-{encoded}"


def assign_cluster_pseudonyms(
    records: Sequence[PatientRecord],
    clusters: Sequence[PatientCluster],
    secret_key: bytes,
    *,
    initial_digest_bytes: int = DEFAULT_PSEUDONYM_BYTES,
) -> PseudonymizationMetrics:
    """Assign deterministic HMAC pseudonyms and mutate clusters/records in place."""

    if not secret_key:
        raise ValueError("Pseudonymization requires a non-empty secret key")
    if not 1 <= initial_digest_bytes <= hashlib.sha256().digest_size:
        raise ValueError("Pseudonym digest length is outside the supported range")

    records_by_ref = {record.record_ref: record for record in records}
    if len(records_by_ref) != len(records):
        raise ValueError("PatientRecord record_ref values must be unique")

    claimed_records: set[str] = set()
    assignment_items: list[tuple[PatientCluster, bytes, bytes]] = []
    unresolved_clusters = 0
    conflict_clusters = 0

    for record in records:
        record.pseudonym_id = None
    for cluster in clusters:
        cluster.pseudonym_id = None
        for record_ref in cluster.member_record_refs:
            if record_ref not in records_by_ref:
                raise ValueError("PatientCluster references an unknown record")
            if record_ref in claimed_records:
                raise ValueError("A record belongs to more than one patient cluster")
            claimed_records.add(record_ref)
            records_by_ref[record_ref].cluster_ref = cluster.cluster_ref

        if cluster.resolution_status == ResolutionStatus.CONFLICT:
            conflict_clusters += 1
            continue
        if cluster.resolution_status == ResolutionStatus.UNRESOLVED and any(
            records_by_ref[record_ref].field_metadata.get("linkage_null_reason")
            for record_ref in cluster.member_record_refs
        ):
            unresolved_clusters += 1
            continue

        identity_status, payload = _identity_payload(cluster, records_by_ref)
        if identity_status != ResolutionStatus.RESOLVED or payload is None:
            cluster.resolution_status = identity_status
            if identity_status == ResolutionStatus.CONFLICT:
                conflict_clusters += 1
            else:
                unresolved_clusters += 1
            continue

        digest = hmac.new(
            secret_key, PSEUDONYM_DOMAIN + payload, hashlib.sha256
        ).digest()
        assignment_items.append((cluster, payload, digest))

    full_digest_payloads: dict[bytes, set[bytes]] = {}
    for _, payload, digest in assignment_items:
        full_digest_payloads.setdefault(digest, set()).add(payload)
    if any(len(payloads) > 1 for payloads in full_digest_payloads.values()):
        raise RuntimeError("Unable to create unique pseudonyms safely")

    digest_lengths = [initial_digest_bytes] * len(assignment_items)
    collision_extensions = 0
    while True:
        token_groups: dict[str, list[int]] = {}
        for index, (_, _, digest) in enumerate(assignment_items):
            token_groups.setdefault(_token(digest, digest_lengths[index]), []).append(index)

        colliding_groups = [
            indices
            for indices in token_groups.values()
            if len({assignment_items[index][1] for index in indices}) > 1
        ]
        if not colliding_groups:
            break
        for indices in colliding_groups:
            for index in indices:
                if digest_lengths[index] >= hashlib.sha256().digest_size:
                    raise RuntimeError("Unable to create unique pseudonyms safely")
                digest_lengths[index] += 1
                collision_extensions += 1

    assigned_tokens: list[str] = []
    for index, (cluster, _, digest) in enumerate(assignment_items):
        pseudonym = _token(digest, digest_lengths[index])
        cluster.pseudonym_id = pseudonym
        assigned_tokens.append(pseudonym)
        for record_ref in cluster.member_record_refs:
            records_by_ref[record_ref].pseudonym_id = pseudonym

    return PseudonymizationMetrics(
        clusters_total=len(clusters),
        assigned_clusters=len(assignment_items),
        unresolved_clusters=unresolved_clusters,
        conflict_clusters=conflict_clusters,
        unique_pseudonyms=len(set(assigned_tokens)),
        collision_extensions=collision_extensions,
    )


class HMACPseudonymizer:
    """Protocol-compatible privacy stage for patient pseudonym decisions."""

    def __init__(
        self,
        patient_categories: frozenset[str] = DEFAULT_PATIENT_CATEGORIES,
    ) -> None:
        self.patient_categories = patient_categories
        self.last_metrics: PseudonymizationMetrics | None = None

    def transform(
        self,
        records: Sequence[PatientRecord],
        clusters: Sequence[PatientCluster],
        secret_key: bytes,
    ) -> list[PrivacyDecision]:
        self.last_metrics = assign_cluster_pseudonyms(records, clusters, secret_key)
        decisions: list[PrivacyDecision] = []
        for record in sorted(records, key=lambda item: item.record_ref):
            if record.pseudonym_id is None:
                continue
            for span in sorted(
                record.detections,
                key=lambda item: (item.field_path, item.start, item.end, item.category),
            ):
                if (
                    span.role == SpanRole.DIRECT_PII
                    and span.category.upper() in self.patient_categories
                ):
                    decisions.append(
                        PrivacyDecision(
                            record_ref=record.record_ref,
                            field_path=span.field_path,
                            start=span.start,
                            end=span.end,
                            transform_type=TransformType.PSEUDONYMIZE,
                            replacement_value=record.pseudonym_id,
                        )
                    )
        return decisions
