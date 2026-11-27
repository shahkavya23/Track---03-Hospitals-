"""Regression and generated class tests for mixed free-text documents."""
from __future__ import annotations

import base64
from datetime import datetime
import json
from pathlib import Path
import re

import pytest

from src.ingestion.format_detect import detect_format
from src.contracts import FileFormat
from src.pipeline import RakshaPipeline
from src.security.independent_scan import scan
from src.serialization.publish_gate import reredact_candidate


@pytest.mark.parametrize("variant", range(50))
def test_mixed_prose_wins_over_embedded_structure(variant):
    delimiter = ["|", "\t", "  "][variant % 3]
    json_line = json.dumps({"patient_name": f"Example Person {variant}", "pulse": 72})
    text = (
        f"Clinical discharge narrative {variant}.\n"
        f"field{delimiter}value\nname{delimiter}Example Person\n"
        f"{json_line}\n"
        "[12/08/24, 8:10 PM] Example Person: medicine taken.\n"
        "Signed electronically.\n"
    )
    fmt, payload = detect_format(f"wrong-{variant}.csv", text)
    assert fmt == FileFormat.TEXT
    assert payload is None


@pytest.mark.parametrize("variant", range(50))
def test_phone_class_variants_are_late_redacted(variant):
    word_forms = [
        "nine eight seven six five four three two one zero",
        "nau aath saat chhe paanch chaar teen do ek shunya",
        "नौ आठ सात छह पाँच चार तीन दो एक शून्य",
    ]
    samples = [
        f"Phone: +971 50 123 {4000 + variant:04d}",
        f"Phone: 011-23{variant:02d}-5678",
        f"Phone: 98765\n{40000 + variant:05d}",
        f"UPI: {7000000000 + variant}@bank",
        "Call " + word_forms[variant % len(word_forms)],
    ]
    result = reredact_candidate(samples[variant % len(samples)])
    assert not scan(result.value)
    assert "[PHONE]" in result.value or "[UPI]" in result.value


@pytest.mark.parametrize("variant", range(50))
def test_identifier_class_variants_are_late_redacted(variant):
    values = [
        f"EPIC ABC{1000000 + variant}",
        f"Account No: {123456780000 + variant} IFSC ABCD0{100000 + variant:06d}",
        f"PM-JAY ID: PMJAY{100000 + variant}",
        f"Donor ID: DN/{2020 + variant % 6}/{1000 + variant}",
        f"mail: person{variant} dot x at gmail dot com",
    ]
    result = reredact_candidate(values[variant % len(values)])
    assert not scan(result.value)
    assert result.replacements >= 1


@pytest.mark.parametrize("variant", range(50))
def test_location_vehicle_and_handle_classes(variant):
    values = [
        f"GPS {20 + variant / 1000:.4f}, {70 + variant / 1000:.4f}",
        f"Vehicle DL {1 + variant % 9:02d} AB {1000 + variant:04d}",
        f"found near Example {variant} mandir",
        f"social @{['helper', 'visitor', 'neighbour'][variant % 3]}_{variant}",
    ]
    result = reredact_candidate(values[variant % len(values)])
    assert not scan(result.value)
    assert result.replacements >= 1


@pytest.mark.parametrize("variant", range(50))
def test_chat_and_nickname_name_classes(variant):
    values = [
        f"[12/08/24, 8:{variant % 60:02d} PM] Person{variant}: I am better",
        f"Patient urf Alias{variant} attended",
        f"message from @ Nick{variant}",
        f"[12/08/24, 8:{variant % 60:02d} PM] علی: بہتر ہے",
    ]
    result = reredact_candidate(values[variant % len(values)])
    assert not scan(result.value)
    assert any(token in result.value for token in ("[PATIENT]", "[PERSON]"))


@pytest.mark.parametrize("variant", range(50))
def test_context_disambiguation_does_not_destroy_clinical_language(variant):
    phrases = [
        "asha means hope in this sentence",
        "prem se samjhaya",
        "Om Shanti prayer offered",
        "Russell's viper bite",
        f"Lot {7781004200 + variant}",
    ]
    value = phrases[variant % len(phrases)]
    result = reredact_candidate(value)
    assert result.value == value


def _parse_dates(text: str) -> list[datetime]:
    return [datetime.strptime(value, "%d/%m/%Y") for value in re.findall(r"\b\d{2}/\d{2}/\d{4}\b", text)]


def test_processable_mixed_document_is_sanitized_with_layout_and_intervals(tmp_path, monkeypatch):
    monkeypatch.setenv("RAKSHA_SECRET", "mixed-document-regression-secret")
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    embedded = base64.b64encode(b"Phone: +971 50 123 4567").decode("ascii")
    raw = (
        "DISCHARGE SUMMARY\n"
        "Patient: Example Person, S/o Example Relative\n"
        "Dr. Example Clinician\n"
        "Admit: 01/08/2024  Discharge: 08/08/2024  POD-7\n"
        "| Test | Result |\n| Hb | 10.4 |\n"
        '{"patient_name":"Nested Person","pulse":72}\n'
        "[08/08/24, 8:10 PM] Chat Person: feeling better\n"
        "Phone: 98765\n43210\n"
        "मरीज: उदाहरण व्यक्ति\n"
        "المریض: علی خان\n"
        f"Attachment: {embedded}\n"
    )
    (input_dir / "discharge.dat").write_text(raw, encoding="utf-8")
    metrics = RakshaPipeline().run(input_dir, tmp_path / "output")
    assert metrics.files_sanitized == 1
    assert metrics.files_quarantined == 0
    output = (tmp_path / "output/sanitized/discharge.dat").read_text(encoding="utf-8")
    assert not scan(output)
    assert "Dr. Example Clinician" in output
    assert [line.count("|") for line in raw.splitlines() if line.startswith("|")] == [
        line.count("|") for line in output.splitlines() if line.startswith("|")
    ]
    json_lines = [line for line in output.splitlines() if line.startswith("{")]
    assert len(json_lines) == 1
    assert json.loads(json_lines[0])["patient_name"] == "[PATIENT]"
    before, after = _parse_dates(raw), _parse_dates(output)
    assert len(before) == len(after) == 2
    assert before[1] - before[0] == after[1] - after[0]
    assert "POD-7" in output


def test_processable_quarantine_metric_and_bait_metric(tmp_path):
    # Sanity shape for the scorecard's two separate quarantine rates.
    from tests.gen.__main__ import generate
    from tests.score import score

    generate(1, 8, "tune", tmp_path / "data")
    out = tmp_path / "out"
    out.mkdir()
    card = score(tmp_path / "data/truth", out)
    assert card["processable_quarantine_rate"] == 1.0
    assert card["unprocessable_quarantine_rate"] == 0.0
