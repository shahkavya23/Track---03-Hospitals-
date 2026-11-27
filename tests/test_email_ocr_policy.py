"""Generated regression classes for email-wrapped OCR discharge text."""
from __future__ import annotations

from datetime import datetime
import re

import pytest

from src.contracts import FieldNode, PatientRecord
from src.privacy.text_policy import (
    entity_decisions,
    prepare_text_records,
    structural_text_decisions,
    temporal_decisions,
)
from src.security.independent_scan import scan
from src.serialization.publish_gate import reredact_candidate
from src.serialization.span_applier import apply_decisions_to_field


def record_for(text: str, index: int = 0) -> PatientRecord:
    return PatientRecord(
        record_ref=f"rec-{index}", source_ref="source", loc="doc",
        original_structure=text,
        fields=[FieldNode("doc", text, "doc", False, "narrative")],
        field_metadata={"record_namespace": f"ns-{index}"},
    )


def apply(record: PatientRecord, decisions) -> str:
    record.privacy_decisions = list(decisions)
    return apply_decisions_to_field(record.fields[0].raw_value, record, "doc")[0]


def alpha(index: int) -> str:
    return chr(65 + index // 26) + chr(65 + index % 26)


@pytest.mark.parametrize("variant", range(50))
def test_entity_mentions_are_whole_role_aware_and_doctor_safe(variant):
    suffix = alpha(variant)
    given = f"Arun{suffix}"
    family = f"Family{suffix}"
    relative = f"Rita{suffix}"
    namesake = f"Other{suffix} {family}"
    doctor = f"Dr. Clinician{suffix} {family}"
    text = (
        f"Patient Name: {given} {family}\n"
        f"Son: {relative}\nAnother patient: {namesake}\nDoctor: {doctor}\n"
        "Temple volunteers shared prasad with prem and asha.\n"
        f"'{relative}' confirmed the history.\n"
    )
    record = record_for(text, variant)
    prepare_text_records([record], b"entity-test")
    output = apply(record, entity_decisions(record))
    assert record.pseudonym_id and record.pseudonym_id in output
    assert "Son: [RELATIVE]" in output
    assert "Another patient: [PERSON]" in output
    assert doctor in output
    assert "prasad with prem and asha" in output
    assert given not in output and relative not in output and namesake not in output


@pytest.mark.parametrize("variant", range(200))
def test_common_word_phrase_guard(variant):
    words = ["prasad", "prem", "asha", "shanti", "bhagwati", "kamal", "daya", "sukh", "ganga", "lakshmi"]
    frames = ["mandir ka {w}", "{w} se samjhaya", "koi {w} nahi", "aaj {w} jagran", "yeh {w} shabd hai"]
    word = words[variant % len(words)]
    phrase = frames[(variant // len(words)) % len(frames)].format(w=word) + f" context {alpha(variant)}"
    text = f"Patient Name: {word.title()} Example\nNote: {phrase}.\n"
    record = record_for(text, variant)
    prepare_text_records([record], b"common-word-test")
    output = apply(record, entity_decisions(record))
    assert phrase in output
    assert record.pseudonym_id in output


@pytest.mark.parametrize("variant", range(50))
def test_email_headers_thread_and_attachment_layout(variant):
    suffix = alpha(variant)
    name = f"Sender{suffix} Example{suffix}"
    text = (
        f"From: {name} <sender{variant}@example.org>\n"
        f"To: Receiver{suffix} Person{suffix} <receiver{variant}@example.org>\n"
        f"Subject: Discharge for {name}\n"
        f"Attachments: IMG_202411{17 + variant % 10:02d}_{name.replace(' ', '_')}.jpg\n\n"
        f"On Thu, 28 Nov 2024, {name} <sender{variant}@example.org> wrote:\n"
        f"> Patient Name: {name}\n> Stable.\n"
    )
    record = record_for(text, variant)
    prepare_text_records([record], b"email-test")
    decisions = entity_decisions(record) + temporal_decisions(record, 9, 5, 90)
    output = reredact_candidate(apply(record, decisions)).value
    assert output.count(">") == text.count(">")
    assert output.count("From:") == output.count("To:") == output.count("Subject:") == 1
    assert "[EMAIL]" in output and name not in output
    assert re.search(r"IMG_20241[12]\d{2}_", output) and "20241117" not in output


@pytest.mark.parametrize("variant", range(50))
def test_ocr_and_mixed_digit_identifiers(variant):
    samples = [
        f"Phone: 4417 9O02 {6600 + variant:04d}",
        f"Mobile: 98l5O {22700 + variant:05d}",
        "PIN: 27l3O4",
        f"Call nine 8 one five zero {22700 + variant}",
        "Aadhaar: 4417 9O02 6618",
    ]
    result = reredact_candidate(samples[variant % len(samples)])
    assert result.replacements >= 1
    assert not scan(result.value)


@pytest.mark.parametrize("variant", range(50))
def test_yearless_compact_ocr_and_weekday_dates_shift(variant):
    day = 1 + variant % 20
    text = (
        "Patient Name: Date Example\n"
        "Export Date: 30/11/2024\n"
        f"DOB: O3/02/1943\nstarted {day:02d}/11\n"
        "Thu, 28 Nov 2024\n"
        "Attachments: IMG_20241117_scan.jpg\n"
        "Kartik Purnima (15/11)\n"
    )
    record = record_for(text, variant)
    prepare_text_records([record], b"date-test")
    output = apply(record, temporal_decisions(record, 3, 5, 90))
    assert "O3/02/1943" not in output
    assert f"started {day:02d}/11" not in output
    assert "20241117" not in output
    assert "Kartik Purnima" not in output and "[EVENT]" in output
    match = re.search(r"\b(?P<weekday>Mon|Tue|Wed|Thu|Fri|Sat|Sun), (?P<date>\d{2} [A-Za-z]{3} \d{4})", output)
    assert match
    assert datetime.strptime(match.group("date"), "%d %b %Y").strftime("%a") == match.group("weekday")


@pytest.mark.parametrize("variant", range(50))
def test_text_age_authority_and_banding(variant):
    age = 20 + variant
    year = 2024 - age
    text = (
        "Patient Name: Age Example\nExport Date: 30/11/2024\n"
        f"DOB: 01/01/{year}\nAge/Sex : {age - 1} Y / M\n"
        f"History says ~{age + 4} yrs. umr {age - 1} yrs.\n"
    )
    record = record_for(text, variant)
    prepare_text_records([record], b"age-test")
    output = apply(record, temporal_decisions(record, -2, 5, 90))
    low = age // 5 * 5
    assert output.count(f"{low}-{low + 4}") == 3
    assert f"{age - 1} Y" not in output and f"~{age + 4}" not in output


@pytest.mark.parametrize("variant", range(50))
def test_full_identifier_classes(variant):
    samples = [
        f"PPO No: PPO/{2020 + variant % 5}/{10000 + variant}",
        f"Senior card SC/UP/{2020 + variant % 5}/{1000 + variant}",
        f"AUTH-{100000 + variant}",
        f"Gumshudgi Report No. GD/{2024}/{100 + variant}",
        f"HC Officer{variant} Example Belt No. {5000 + variant}",
        f"https://example.org/group/family-{variant}/post/{9000 + variant}",
        f"Qr. No. B-{10 + variant}",
        f"CCTV CAM ID GATE_{variant} @ 18:45:00",
    ]
    result = reredact_candidate(samples[variant % len(samples)])
    assert result.replacements >= 1
    assert not scan(result.value)


@pytest.mark.parametrize("variant", range(50))
def test_multiscript_relation_and_role_names(variant):
    samples = [
        f"Patient Name: Example Person\nपुत्र: उदाहरण {['लाल', 'कुमार', 'देवी'][variant % 3]}\nबहू: व्यक्ति देवी",
        f"Patient Name: Example Person\nبیٹا: علی خان\nبیوی: زینب بیگم",
        f"Patient Name: Example Person\nकार्यकर्ता: सीमा देवी",
        f"Patient Name: Example Person\n'{['भगवती', 'चिंटू', 'रीना'][variant % 3]}' आया",
    ]
    record = record_for(samples[variant % len(samples)], variant)
    prepare_text_records([record], b"script-test")
    output = apply(record, entity_decisions(record))
    assert record.pseudonym_id in output
    assert any(token in output for token in ("[RELATIVE]", "[STAFF]", "[PERSON]"))


@pytest.mark.parametrize("variant", range(50))
def test_quasi_identifier_phrase_classes(variant):
    samples = [
        f"Retd. Station Master at Junction {variant} (1965-2003)",
        f"School Example Academy, class {1 + variant % 12}-A",
        f"WhatsApp group Family Circle {variant}",
        f"CCTV camera location near Gate {variant}",
        f"platform {1 + variant % 9}, stall A-{variant}",
        f"son's job at City Office {variant}",
    ]
    record = record_for(samples[variant % len(samples)], variant)
    output = apply(record, structural_text_decisions(record))
    assert output != record.fields[0].raw_value
    assert any(token in output for token in ("[OCCUPATION]", "[SCHOOL]", "[IDENTITY_HINT]", "[ADDRESS]"))
