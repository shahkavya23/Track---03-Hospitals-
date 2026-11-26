"""Acceptance tests for the structure-aware Secret Wards stress register."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata

from src.pipeline import RakshaPipeline


FIXTURE = Path(__file__).parents[1] / "My personal testing" / "t1"


def _normalized(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.translate(str.maketrans("०१२३४५६७८९", "0123456789"))
    return re.sub(r"[\s-]+", "", value)


def _parse_date(value: str, month_first: bool = False) -> datetime:
    if re.fullmatch(r"\d{10}", value):
        return datetime.fromtimestamp(int(value), timezone.utc).replace(tzinfo=None)
    if value.endswith("Z"):
        return datetime.fromisoformat(value[:-1] + "+00:00").replace(tzinfo=None)
    formats = ["%m/%d/%Y"] if month_first else []
    formats += ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d-%b-%y"]
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise AssertionError(f"Unparseable test date format: {value!r}")


def _run(root: Path, secret: str, output_name: str) -> Path:
    input_dir = root / "input"
    input_dir.mkdir(exist_ok=True)
    shutil.copyfile(FIXTURE, input_dir / "ymc_ipd_register_2024.csv")
    old = os.environ.get("RAKSHA_SECRET")
    os.environ["RAKSHA_SECRET"] = secret
    try:
        output = root / output_name
        RakshaPipeline().run(input_dir, output)
        return output
    finally:
        if old is None:
            os.environ.pop("RAKSHA_SECRET", None)
        else:
            os.environ["RAKSHA_SECRET"] = old


def test_secret_wards_structure_leaks_clinical_and_determinism() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        out1 = _run(root, "stress-secret-one", "out1")
        out2 = _run(root, "stress-secret-one", "out2")
        out3 = _run(root, "stress-secret-two", "out3")

        input_rows = list(csv.reader(FIXTURE.open(encoding="utf-8", newline="")))
        sanitized_path = out1 / "sanitized" / "ymc_ipd_register_2024.csv"
        output_rows = list(csv.reader(sanitized_path.open(encoding="utf-8", newline="")))
        assert len(output_rows) == len(input_rows) == 17
        assert all(len(row) == 14 for row in output_rows)
        assert output_rows[0][:-1] == input_rows[0][:-1]
        assert output_rows[0][-1] == "Remarks (verified by [STAFF] [PHONE])"
        assert output_rows[15] == [""] * 14
        assert output_rows[16][0] == "TOTAL: 14 rows (13 unique)"
        assert "[USERNAME]" in output_rows[16][1]
        assert "[DATE]" in output_rows[16][1]
        assert "[IP]" in output_rows[16][1]

        all_output = "\n".join(
            path.read_text(encoding="utf-8")
            for path in out1.rglob("*")
            if path.is_file()
        )
        normalized = _normalized(all_output)
        leaks = [
            "Kureshi", "Qureshi", "Arif", "Gita", "Shabnam", "Bano", "Parvati",
            "Ravi", "Pappu", "Imran", "Meera", "Raju", "Gudda", "Kallo", "Kamla",
            "Sanjay", "Maurya", "Kavita", "kavita.s", "10.0.4.17", "20190034412",
            "9839014427", "9935112004", "7715330290214", "cricketer", "gold tooth",
            "UNRESOLVED",
        ]
        assert not [item for item in leaks if _normalized(item) in normalized]

        preserved = [
            "Dr. Wilson Thomas", "Dr. R. C. Tiwari", "Dr. Ramesh Chandra Tiwari",
            "Dr. Kiran Bala", "Dr. Neha Saxena", "Dr. Farhan Siddiqui",
            "Hansen's disease", "Down syndrome", "Wilson's disease", "Bell's palsy",
            "Addison's disease", "Organophosphate poisoning", "Hydrocortisone 20 mg 1-0-1",
            "Midazolam 0.2 mg/kg", "Plt 1,46,000", "Plt 146000", "GCS 8/15", "Nani",
        ]
        assert not [item for item in preserved if item not in all_output]

        assert [row[2] for row in output_rows[1:15]] == [
            "45-49", "30-34", "10-14", "40-44", "50-54", "25-29", "<1",
            "45-49", "45-49", "45-49", "35-39", "30-34", "90+", "5-9",
        ]

        for idx in range(1, 15):
            if input_rows[idx][8] and input_rows[idx][9]:
                month_first = idx == 7
                before = _parse_date(input_rows[idx][9], month_first) - _parse_date(input_rows[idx][8], month_first)
                after = _parse_date(output_rows[idx][9], month_first) - _parse_date(output_rows[idx][8], month_first)
                assert after == before

        # Encounter references use the same HMAC token as their source row.
        assert output_rows[7][0] in output_rows[8][13]
        assert output_rows[11][0] in output_rows[12][13]
        assert "1201" not in output_rows[10][13]
        assert "oldest patient" not in all_output.casefold()
        assert "Pneumonia" in output_rows[13][11]
        assert output_rows[4][7] == "[ID_MARK]"
        assert "ambulance 108" in output_rows[4][4]
        assert "EMT [STAFF]" in output_rows[4][4]

        assert [output_rows[idx][5] for idx in (1, 2, 5, 11, 12)] == ["Sonpur"] * 5
        assert all(output_rows[idx][5] == "[ADDRESS]" for idx in (3, 4))
        assert all(output_rows[idx][5] == "271XXX region" for idx in (6, 7, 8, 9, 13, 14))
        assert "Kachhwa Khurd" not in all_output
        assert output_rows[14][5] in output_rows[14][4]
        assert output_rows[11][8][:10] == output_rows[12][8][:10]

        records = [json.loads(line) for line in (out1 / "records.jsonl").read_text(encoding="utf-8").splitlines()]
        assert len(records) == 14
        assert all(record["patient"] and record["patient"].startswith("PSN-") for record in records)
        assert records[8]["patient"] == records[9]["patient"]
        assert records[8]["patient"].startswith("PSN-")
        patient_ids = [record["patient"] for record in records]
        assert len(set(patient_ids)) == 13
        assert records[10]["patient"] != records[4]["patient"]
        assert records[6]["patient"] != records[7]["patient"]
        report = json.loads((out1 / "report.json").read_text(encoding="utf-8"))
        assert report["counts"]["records_processed"] == 14

        relative = Path("sanitized/ymc_ipd_register_2024.csv")
        assert (out1 / relative).read_bytes() == (out2 / relative).read_bytes()
        assert (out1 / relative).read_bytes() != (out3 / relative).read_bytes()
