import io
import json
from pathlib import Path
import pytest
import backend_server as api
from main import main
from src.security.independent_scan import scan


def request(path, payload=None):
    handler = object.__new__(api.RakshaAPIHandler)
    body = json.dumps(payload or {}).encode()
    handler.path = path
    handler.headers = {'Content-Length': str(len(body)), 'Content-Type':'application/json'}
    handler.rfile = io.BytesIO(body)
    captured = []
    handler._send_json = lambda status, value: captured.append((status, value))
    api.RakshaAPIHandler.do_POST(handler)
    return captured[-1]


@pytest.mark.parametrize('variant', range(50))
def test_ui_upload_and_cli_use_same_pipeline(tmp_path, monkeypatch, variant):
    monkeypatch.setenv('RAKSHA_SECRET', 'incident-parity-key')
    monkeypatch.setattr(api, 'UI_WORKSPACE', tmp_path/'ui')
    monkeypatch.setattr(api, 'INPUT_DIR', tmp_path/'ui/input')
    monkeypatch.setattr(api, 'OUTPUT_DIR', tmp_path/'ui/output')
    suffix = ['csv', 'txt', 'dat', '', 'log'][variant % 5]
    name = 'upload' + ('.'+suffix if suffix else '')
    delimiter = [';', ',', '\t'][variant % 3]
    content = delimiter.join(['patient_name', 'phone', 'abha', 'doctor', 'notes']) + '\n'
    for idx in range(3):
        content += delimiter.join([f'Synthetic Subject{idx}', str(9876501000+idx),
            str(91000000001000+idx), 'Dr. Example Clinician', 'BP 120/80']) + '\n'
    assert request('/api/upload', {'filename':name, 'content':content})[0] == 200
    status, result = request('/api/run')
    assert status == 200
    assert result['verification']['verified'] is False
    sanitized = api.OUTPUT_DIR/'sanitized'/name
    assert sanitized.exists()
    cleaned = sanitized.read_text(encoding='utf-8')
    assert cleaned.count('Dr. Example Clinician') == 3
    assert '[REDACTED-' not in cleaned
    assert not scan(cleaned)
    cli = tmp_path/'cli'
    assert main(['--input', str(api.INPUT_DIR), '--output', str(cli), '--policy',
                 str(Path(api.__file__).parent/'config/policy.yaml')]) == 0
    for path in cli.rglob('*'):
        if not path.is_file():
            continue
        other = api.OUTPUT_DIR/path.relative_to(cli)
        if path.name == 'report.json':
            reports = [json.loads(p.read_text()) for p in (path,other)]
            for report in reports:
                report.pop('timing'); report.pop('resources')
            assert reports[0] == reports[1]
        else:
            assert path.read_bytes() == other.read_bytes()


@pytest.mark.parametrize('variant', range(50))
def test_masked_identifier_and_case_marker_grammar(variant):
    from src.detection.regex_rules import detect_regex_candidates
    from src.privacy.structured import _EXTRA_PATTERNS
    separator = [' ', '-', ''][variant % 3]
    masked = separator.join(['XXXX', 'XXXX', str(2000+variant)])
    assert any(span.category == 'AADHAAR' for span in detect_regex_candidates(masked))
    no_number = f'first case reported in season {variant % 10}'
    assert not any(pattern.search(no_number) for pattern, token in _EXTRA_PATTERNS if token == '[CASE_NO]')
    assert any(pattern.search(f'MLC {100+variant}/2024') for pattern, token in _EXTRA_PATTERNS if token == '[CASE_NO]')


@pytest.mark.parametrize('variant', range(50))
def test_independent_phone_scan_does_not_need_registry(variant):
    digits = ['0123456789','०१२३४५६७८९','۰۱۲۳۴۵۶۷۸۹','੦੧੨੩੪੫੬੭੮੯'][variant % 4]
    value = '9876501234'.translate(str.maketrans('0123456789', digits))
    value = ['',' ','-','\u200b','\u200c'][variant % 5].join(value)
    assert scan('Phone: '+value)['PHONE'] == 1
