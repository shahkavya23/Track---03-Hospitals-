"""Deterministic patient-level date shifting with timeline preservation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import hmac
from typing import Sequence

from src.contracts import (
    PatientCluster,
    PatientRecord,
    PrivacyDecision,
    ResolutionStatus,
    SpanRole,
    TransformType,
)


DATE_SHIFT_DOMAIN = b"raksha:v1:date-shift\0"
DEFAULT_DATE_CATEGORIES = frozenset(
    {"DATE", "VISIT_DATE", "ADMISSION_DATE", "DISCHARGE_DATE", "DOB", "DATE_OF_BIRTH"}
)


@dataclass(frozen=True, slots=True)
class DateShiftMetrics:
    shifted_records: int
    shifted_values: int
    clusters_with_offsets: int


def derive_date_offset(secret_key: bytes, pseudonym: str, max_abs_days: int = 180) -> int:
    """Derive a non-zero offset in ``[-max_abs_days, max_abs_days]``."""

    if not secret_key:
        raise ValueError("Date shifting requires a non-empty secret key")
    if max_abs_days < 1:
        raise ValueError("Date-shift range must contain at least one day")
    digest = hmac.new(
        secret_key,
        DATE_SHIFT_DOMAIN + pseudonym.encode("ascii"),
        hashlib.sha256,
    ).digest()
    position = int.from_bytes(digest[:8], "big") % (2 * max_abs_days)
    return position - max_abs_days if position < max_abs_days else position - max_abs_days + 1


def shift_date_value(value: str, offset_days: int) -> str:
    """Shift a supported date/datetime while preserving its representation."""

    if offset_days == 0:
        raise ValueError("Date-shift offset must be non-zero")
    stripped = value.strip()
    leading = value[: len(value) - len(value.lstrip())]
    trailing = value[len(value.rstrip()) :]

    if "T" in stripped:
        had_z = stripped.endswith("Z")
        try:
            parsed = datetime.fromisoformat(
                stripped[:-1] + "+00:00" if had_z else stripped
            )
        except ValueError as exc:
            raise ValueError("Unsupported or invalid date value") from exc
        shifted = (parsed + timedelta(days=offset_days)).isoformat()
        if had_z:
            shifted = shifted.replace("+00:00", "Z")
        return f"{leading}{shifted}{trailing}"

    formats = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d")
    for date_format in formats:
        try:
            parsed = datetime.strptime(stripped, date_format)
        except ValueError:
            continue
        shifted = (parsed + timedelta(days=offset_days)).strftime(date_format)
        return f"{leading}{shifted}{trailing}"
    raise ValueError("Unsupported or invalid date value")


class PatientDateShifter:
    def __init__(
        self,
        max_abs_days: int = 180,
        date_categories: frozenset[str] = DEFAULT_DATE_CATEGORIES,
    ) -> None:
        self.max_abs_days = max_abs_days
        self.date_categories = date_categories
        self.last_metrics: DateShiftMetrics | None = None

    def transform(
        self,
        records: Sequence[PatientRecord],
        clusters: Sequence[PatientCluster],
        secret_key: bytes,
    ) -> list[PrivacyDecision]:
        clusters_by_ref = {cluster.cluster_ref: cluster for cluster in clusters}
        offsets: dict[str, int] = {}
        for cluster in clusters:
            if (
                cluster.resolution_status == ResolutionStatus.RESOLVED
                and cluster.pseudonym_id is not None
            ):
                offsets[cluster.cluster_ref] = derive_date_offset(
                    secret_key, cluster.pseudonym_id, self.max_abs_days
                )

        decisions: list[PrivacyDecision] = []
        shifted_record_refs: set[str] = set()
        for record in sorted(records, key=lambda item: item.record_ref):
            cluster = clusters_by_ref.get(record.cluster_ref or "")
            if cluster is None or cluster.cluster_ref not in offsets:
                continue
            fields_by_path = {field.field_path: field for field in record.fields}
            offset = offsets[cluster.cluster_ref]
            for span in sorted(
                record.detections,
                key=lambda item: (item.field_path, item.start, item.end, item.category),
            ):
                if span.role == SpanRole.CLINICAL_PROTECTED:
                    continue
                if span.category.upper() not in self.date_categories:
                    continue
                field = fields_by_path.get(span.field_path)
                if field is None or span.end > len(field.raw_value):
                    raise ValueError("Date span does not match its record field")
                raw_date = field.raw_value[span.start : span.end]
                try:
                    replacement = shift_date_value(raw_date, offset)
                except ValueError as exc:
                    raise ValueError("Detected date could not be shifted safely") from exc
                decisions.append(
                    PrivacyDecision(
                        record_ref=record.record_ref,
                        field_path=span.field_path,
                        start=span.start,
                        end=span.end,
                        transform_type=TransformType.DATE_SHIFT,
                        replacement_value=replacement,
                        params={"offset_days": offset},
                        clinical_constraints=("PRESERVE_INTERVALS", "PRESERVE_TIMEZONE"),
                    )
                )
                shifted_record_refs.add(record.record_ref)

        self.last_metrics = DateShiftMetrics(
            shifted_records=len(shifted_record_refs),
            shifted_values=len(decisions),
            clusters_with_offsets=len(offsets),
        )
        return decisions
