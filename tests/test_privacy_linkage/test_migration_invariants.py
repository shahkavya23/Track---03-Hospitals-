from src.ingestion.parsers.json_parser import parse_json_document
from src.privacy.structured import classify_field, generalize_age
from src.privacy.structured import _record_token


def test_nested_people_segment_before_flattening():
    payload = {'groups': {'house': {'head': {'name': 'Guardian'}, 'members': [
        {'name': 'Person A', 'visits': [{'note': 'fever'}]},
        {'name': 'Person B', 'visits': [{'note': 'cough'}]},
    ]}}}
    counter = iter(range(10))
    records = parse_json_document(payload, 's', lambda: str(next(counter)))
    patients = [r for r in records if not r.field_metadata.get('metadata_only')]
    assert len(patients) == 2
    assert not any('Guardian' in f.raw_value for r in patients for f in r.fields)


def test_dob_is_date_and_age_range_is_truthful():
    assert classify_field('dob') == 'DOB'
    assert classify_field('date_of_birth') == 'DOB'
    assert generalize_age('60-65') == '60-69'


def test_record_tokens_are_namespaced():
    assert _record_token(b'key', 'IPD/2024/1201', 'hospital-a') == _record_token(b'key', '1201', 'hospital-a')
    assert _record_token(b'key', '1201', 'hospital-a') != _record_token(b'key', '1201', 'hospital-b')


def test_family_output_pointers_resolve(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    from src.pipeline import RakshaPipeline
    fixture = Path(__file__).parents[1] / 'fixtures' / 'family_export_v1.json'
    source = tmp_path / 'input'
    source.mkdir()
    (source / 'family.json').write_bytes(fixture.read_bytes())
    monkeypatch.setenv('RAKSHA_SECRET', 'family-regression-key')
    out = tmp_path / 'output'
    RakshaPipeline().run(source, out)
    payload = json.loads((out / 'sanitized/family.json').read_text(encoding='utf-8'))
    rows = [json.loads(line) for line in (out / 'records.jsonl').read_text().splitlines()]
    assert len(rows) == 8
    assert len({row['patient'] for row in rows}) == 8
    for row in rows:
        current = payload
        for token in row['loc'].strip('/').split('/'):
            token = token.replace('~1', '/').replace('~0', '~')
            current = current[int(token)] if isinstance(current, list) else current[token]
        assert row['patient'] in json.dumps(current)
    assert payload['export']['operator']['login'] == '[USERNAME]'
    monkeypatch.setenv('TZ', 'Pacific/Honolulu')
    monkeypatch.chdir(tmp_path)
    out2 = tmp_path / 'output2'
    RakshaPipeline().run(source, out2)
    assert (out / 'sanitized/family.json').read_bytes() == (out2 / 'sanitized/family.json').read_bytes()
    assert (out / 'records.jsonl').read_bytes() == (out2 / 'records.jsonl').read_bytes()
    reports = [json.loads((p / 'report.json').read_text()) for p in (out, out2)]
    for report in reports:
        report.pop('timing')
        report.pop('resources')
    assert reports[0] == reports[1]
