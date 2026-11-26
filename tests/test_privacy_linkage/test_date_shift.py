"""Tests for deterministic patient-level date shifting."""

from __future__ import annotations

from datetime import date, datetime
import unittest

from src.contracts import (
    DetectionSpan,
    FieldNode,
    PatientCluster,
    PatientRecord,
    ResolutionStatus,
    SpanRole,
)
from src.privacy.date_shift import (
    PatientDateShifter,
    derive_date_offset,
    shift_date_value,
)


def _dated_record(record_ref: str, admission: str, discharge: str) -> PatientRecord:
    record = PatientRecord(
        record_ref=record_ref,
        source_ref=f"source_{record_ref}",
        loc="row:0",
        original_structure={},
        fields=[
            FieldNode("admission", admission, "admission", False),
            FieldNode("discharge", discharge, "discharge", False),
        ],
        cluster_ref="clu_1",
        pseudonym_id="PSN-SYNTHETIC",
    )
    record.detections = [
        DetectionSpan(
            record_ref,
            "admission",
            0,
            len(admission),
            "ADMISSION_DATE",
            SpanRole.QUASI_IDENTIFIER,
            1.0,
            "synthetic",
        ),
        DetectionSpan(
            record_ref,
            "discharge",
            0,
            len(discharge),
            "DISCHARGE_DATE",
            SpanRole.QUASI_IDENTIFIER,
            1.0,
            "synthetic",
        ),
    ]
    return record


class DateOffsetTests(unittest.TestCase):
    def test_offset_is_deterministic_nonzero_and_bounded(self) -> None:
        first = derive_date_offset(b"secret-alpha", "PSN-SYNTHETIC", 180)
        second = derive_date_offset(b"secret-alpha", "PSN-SYNTHETIC", 180)

        self.assertEqual(first, second)
        self.assertNotEqual(first, 0)
        self.assertLessEqual(abs(first), 180)

    def test_different_test_secrets_change_offset(self) -> None:
        self.assertNotEqual(
            derive_date_offset(b"secret-alpha", "PSN-SYNTHETIC", 180),
            derive_date_offset(b"secret-beta", "PSN-SYNTHETIC", 180),
        )


class DateRepresentationTests(unittest.TestCase):
    def test_leap_year_and_year_boundary(self) -> None:
        self.assertEqual(shift_date_value("2024-02-29", 1), "2024-03-01")
        self.assertEqual(shift_date_value("31/12/2025", 1), "01/01/2026")

    def test_timezone_and_time_are_preserved(self) -> None:
        shifted = shift_date_value("2026-03-10T14:30:00+05:30", 13)
        parsed = datetime.fromisoformat(shifted)

        self.assertEqual(parsed.date(), date(2026, 3, 23))
        self.assertEqual(parsed.hour, 14)
        self.assertEqual(parsed.minute, 30)
        self.assertEqual(parsed.utcoffset().total_seconds(), 19800)

    def test_invalid_date_raises_safe_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported or invalid date value"):
            shift_date_value("not-a-date", 10)


class PatientTimelineTests(unittest.TestCase):
    def test_all_patient_dates_use_one_offset_and_preserve_stay(self) -> None:
        records = [
            _dated_record("rec_1", "2026-03-10", "2026-03-19"),
            _dated_record("rec_2", "2026-06-01", "2026-06-04"),
        ]
        cluster = PatientCluster(
            "clu_1",
            ("rec_1", "rec_2"),
            ResolutionStatus.RESOLVED,
            pseudonym_id="PSN-SYNTHETIC",
        )
        shifter = PatientDateShifter(max_abs_days=180)

        decisions = shifter.transform(records, [cluster], b"secret-alpha")

        self.assertEqual(len(decisions), 4)
        offsets = {decision.params["offset_days"] for decision in decisions}
        self.assertEqual(len(offsets), 1)
        replacements = {
            (decision.record_ref, decision.field_path): decision.replacement_value
            for decision in decisions
        }
        first_admission = date.fromisoformat(replacements[("rec_1", "admission")])
        first_discharge = date.fromisoformat(replacements[("rec_1", "discharge")])
        second_admission = date.fromisoformat(replacements[("rec_2", "admission")])
        second_discharge = date.fromisoformat(replacements[("rec_2", "discharge")])
        self.assertEqual((first_discharge - first_admission).days, 9)
        self.assertEqual((second_discharge - second_admission).days, 3)
        self.assertEqual(shifter.last_metrics.shifted_records, 2)

    def test_unresolved_patient_dates_are_not_shifted(self) -> None:
        record = _dated_record("rec_1", "2026-03-10", "2026-03-19")
        cluster = PatientCluster(
            "clu_1", ("rec_1",), ResolutionStatus.UNRESOLVED
        )

        decisions = PatientDateShifter().transform(
            [record], [cluster], b"secret-alpha"
        )

        self.assertEqual(decisions, [])


if __name__ == "__main__":
    unittest.main()
