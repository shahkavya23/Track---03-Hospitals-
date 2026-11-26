"""Adaptive quasi-identifier generalization with clinical preservation."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from src.contracts import (
    PatientRecord,
    PrivacyDecision,
    SpanRole,
    TransformType,
)


DEFAULT_PROFILE_ATTRIBUTES = (
    "ages",
    "genders",
    "geo_keys",
    "diagnoses",
    "visit_years",
)


@dataclass(frozen=True, slots=True)
class GeneralizationPolicy:
    k_threshold: int = 3
    moderate_age_width: int = 5
    high_age_width: int = 10
    moderate_pin_prefix: int = 3
    high_pin_prefix: int = 2

    def __post_init__(self) -> None:
        if self.k_threshold < 2:
            raise ValueError("k threshold must be at least 2")
        if self.moderate_age_width < 1 or self.high_age_width < 1:
            raise ValueError("Age-band widths must be positive")


@dataclass(frozen=True, slots=True)
class GeneralizationMetrics:
    low_risk_records: int
    moderate_risk_records: int
    high_risk_records: int
    generalized_records: int
    decisions: int


def age_band(age: int, width: int) -> str:
    """Return a truthful inclusive age band containing ``age``."""

    if age < 0 or age > 130:
        raise ValueError("Age is outside the supported range")
    if age >= 90:
        return "90+"
    lower = (age // width) * width
    upper = lower + width - 1
    return f"{lower}-{upper}"


def generalize_pin(pin: str, prefix_length: int) -> str:
    digits = "".join(character for character in pin if character.isdigit())
    if len(digits) != 6 or not 1 <= prefix_length < 6:
        raise ValueError("PIN code cannot be generalized safely")
    return digits[:prefix_length] + "X" * (6 - prefix_length)


def _first(record: PatientRecord, attribute: str) -> str:
    values = sorted(
        {
            value.strip()
            for value in record.extracted_patient_attributes.get(attribute, [])
            if value.strip()
        }
    )
    return values[0] if values else "<MISSING>"


def equivalence_class_sizes(
    records: Sequence[PatientRecord],
    attributes: Sequence[str] = DEFAULT_PROFILE_ATTRIBUTES,
) -> dict[str, int]:
    """Measure the size of each record's quasi-identifier equivalence class."""

    profiles = {
        record.record_ref: tuple(_first(record, attribute) for attribute in attributes)
        for record in records
    }
    counts = Counter(profiles.values())
    return {record_ref: counts[profile] for record_ref, profile in profiles.items()}


class AdaptiveGeneralizer:
    def __init__(self, policy: GeneralizationPolicy | None = None) -> None:
        self.policy = policy or GeneralizationPolicy()
        self.last_metrics: GeneralizationMetrics | None = None

    def transform(self, records: Sequence[PatientRecord]) -> list[PrivacyDecision]:
        class_sizes = equivalence_class_sizes(records)
        decisions: list[PrivacyDecision] = []
        risk_counts = Counter()
        generalized_records: set[str] = set()

        for record in sorted(records, key=lambda item: item.record_ref):
            size = class_sizes[record.record_ref]
            if size >= self.policy.k_threshold:
                tier = "low"
            elif size > 1:
                tier = "moderate"
            else:
                tier = "high"
            risk_counts[tier] += 1
            if tier == "low":
                continue

            fields_by_path = {field.field_path: field for field in record.fields}
            for span in sorted(
                record.detections,
                key=lambda item: (item.field_path, item.start, item.end, item.category),
            ):
                if span.role == SpanRole.CLINICAL_PROTECTED:
                    continue
                if span.role != SpanRole.QUASI_IDENTIFIER:
                    continue
                field = fields_by_path.get(span.field_path)
                if field is None or span.end > len(field.raw_value):
                    raise ValueError("Quasi-identifier span does not match its field")
                raw_value = field.raw_value[span.start : span.end]
                category = span.category.upper()
                replacement: str | None = None
                constraint: str | None = None

                if category in {"AGE", "PATIENT_AGE"}:
                    try:
                        numeric_age = int(raw_value.strip())
                    except ValueError as exc:
                        raise ValueError("Detected age cannot be generalized safely") from exc
                    width = (
                        self.policy.moderate_age_width
                        if tier == "moderate"
                        else self.policy.high_age_width
                    )
                    replacement = age_band(numeric_age, width)
                    constraint = "AGE_BAND_CONTAINS_TRUE_AGE"
                elif category in {"PIN", "PIN_CODE", "POSTAL_CODE"}:
                    prefix = (
                        self.policy.moderate_pin_prefix
                        if tier == "moderate"
                        else self.policy.high_pin_prefix
                    )
                    replacement = generalize_pin(raw_value, prefix)
                elif category in {"VILLAGE", "LOCATION", "GEOGRAPHY"}:
                    target_attribute = "districts" if tier == "moderate" else "states"
                    candidate = _first(record, target_attribute)
                    if candidate != "<MISSING>":
                        replacement = candidate

                if replacement is None:
                    continue
                decisions.append(
                    PrivacyDecision(
                        record_ref=record.record_ref,
                        field_path=span.field_path,
                        start=span.start,
                        end=span.end,
                        transform_type=TransformType.GENERALIZE,
                        replacement_value=replacement,
                        params={"risk_tier": tier, "equivalence_size": size},
                        clinical_constraints=(constraint,) if constraint else (),
                    )
                )
                generalized_records.add(record.record_ref)

        self.last_metrics = GeneralizationMetrics(
            low_risk_records=risk_counts["low"],
            moderate_risk_records=risk_counts["moderate"],
            high_risk_records=risk_counts["high"],
            generalized_records=len(generalized_records),
            decisions=len(decisions),
        )
        return decisions
