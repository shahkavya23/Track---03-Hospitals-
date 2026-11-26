from src.ingestion.parsers.json_parser import parse_json_document
from src.privacy.structured import classify_field, generalize_age


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
