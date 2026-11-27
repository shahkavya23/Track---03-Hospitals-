import pytest
from src.contracts import FileFormat
from src.ingestion.format_detect import detect_format


@pytest.mark.parametrize('variant', range(60))
def test_parser_selected_by_content(variant):
    suffix = ['.csv', '.txt', '.dat', '', '.log'][variant % 5]
    delimiter = [',', ';', '\t', '|'][variant % 4]
    content = delimiter.join(['patient_name', 'age', 'phone']) + '\n'
    content += '\n'.join(delimiter.join([f'Example Person{i}', '35', str(9876000000+i)]) for i in range(3))
    fmt, _ = detect_format('dump'+suffix, content)
    assert fmt == (FileFormat.TSV if delimiter == '\t' else FileFormat.CSV)


@pytest.mark.parametrize('variant', range(50))
def test_json_and_fhir_in_arbitrary_extensions(variant):
    suffix = ['.txt', '.dat', '.log', '', '.csv'][variant % 5]
    fhir = variant % 2 == 0
    text = '{"resourceType":"Patient","name":[{"text":"Synthetic Person"}]}' if fhir else '{"patient_name":"Synthetic Person"}'
    assert detect_format('upload'+suffix, text)[0] == (FileFormat.FHIR_R4 if fhir else FileFormat.JSON)
