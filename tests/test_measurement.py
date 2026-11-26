import builtins
import hashlib
import io
import json
from pathlib import Path
import shutil
import pytest
from tests.gen.__main__ import generate
from tests.score import score
from tests.score import norm
from tests.guarded_runtime import reject_truth_access


@pytest.mark.parametrize('index', range(50))
def test_runtime_audit_guard_denies_oracle_paths(index):
    with pytest.raises(PermissionError, match='BENCHMARK_TRUTH_ACCESS_DENIED'):
        reject_truth_access('open', (f'dataset-{index}/truth/entities.json', 'r', 0))


@pytest.mark.parametrize('variant', range(60))
def test_scanner_normalization_digit_spacing_variants(variant):
    digits = '1234567890'
    alphabets = ['0123456789', '०१२३४५६७८९', '۰۱۲۳۴۵۶۷۸۹', '੦੧੨੩੪੫੬੭੮੯']
    translated = digits.translate(str.maketrans('0123456789', alphabets[variant % 4]))
    separator = ['', ' ', '-', '\u200b', '\u200c'][variant % 5]
    assert norm(separator.join(translated)) == digits


def test_supported_localities_are_not_pii_leaks(tmp_path):
    generate(1, 50, 'tune', tmp_path/'data')
    copied = tmp_path/'copy'
    shutil.copytree(tmp_path/'data/input', copied/'sanitized')
    card = score(tmp_path/'data/truth', copied)
    assert card['permitted_locality_observations'] > 0
    assert 'type:LOCALITY' not in card['pii_recall']
    assert card['raw_copy_count'] == 3
    assert card['penalty_breakdown']['raw_copy'] == 30


@pytest.mark.parametrize('variant', range(50))
def test_canary_on_encoded_attachment_is_counted_once(tmp_path, variant):
    import base64
    generate(1, 8, 'tune', tmp_path/'data')
    truth = tmp_path/'data/truth'
    value = json.loads((truth/'canaries.json').read_text())[0]
    out = tmp_path/'out'
    out.mkdir()
    key = ['data', 'bytes_b64', 'attachment_base64'][variant % 3]
    nested = {key: base64.b64encode((value+' '+value).encode()).decode()}
    for _ in range(variant % 7):
        nested = {'children': [nested]}
    (out/'attachment.json').write_text(json.dumps(nested))
    card = score(truth, out)
    assert card['canary_count'] == 1
    assert card['canary_penalty'] == 20


def test_holdout_templates_frozen():
    path = Path(__file__).parent / 'gen/holdout.py'
    assert hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest() == 'f01fec78f36ef8316df7b225a905ea2b84e1633066f703bc97e1ac687b161a8b'


def test_generator_deterministic(tmp_path):
    for name in ('a', 'b'):
        generate(1, 50, 'tune', tmp_path/name)
    for path in sorted((tmp_path/'a').rglob('*')):
        if path.is_file():
            assert path.read_bytes() == (tmp_path/'b'/path.relative_to(tmp_path/'a')).read_bytes()


def test_surface_matrix_inventory(tmp_path):
    generate(1, 10, 'tune', tmp_path/'dataset', surface_variants=60)
    rows = [json.loads(line) for line in (tmp_path/'dataset/truth/pii_inventory.jsonl').read_text(encoding='utf-8').splitlines()]
    probes = [row for row in rows if row['loc'] == 'metadata']
    assert len(probes) == 120
    assert {row['surface'] for row in probes} == {'header', 'key', 'filename', 'attachment', 'free text', 'FHIR narrative', 'cell'}
    assert {row['script'] for row in probes} == {'Latin', 'Devanagari', 'Urdu', 'Gurmukhi'}


def test_scorer_copy_delete_canary(tmp_path):
    generate(1, 50, 'tune', tmp_path/'data')
    truth = tmp_path/'data/truth'
    empty = tmp_path/'empty'
    empty.mkdir()
    deletion = score(truth, empty)
    assert 15 <= deletion['total'] <= 21
    copied = tmp_path/'copy'
    shutil.copytree(tmp_path/'data/input', copied/'sanitized')
    identity = score(truth, copied)
    assert identity['categories']['privacy'] == 0
    baseline = score(truth, empty)
    canary = json.loads((truth/'canaries.json').read_text())[0]
    (empty/'log.txt').write_text(canary + '\n' + canary)
    leaked = score(truth, empty)
    assert leaked['canary_penalty'] - baseline['canary_penalty'] == 20
    assert leaked['canary_count'] == 1


def test_runtime_isolation(tmp_path, monkeypatch):
    from src.pipeline import RakshaPipeline
    generate(2, 10, 'tune', tmp_path/'data')
    original_builtin, original_io = builtins.open, io.open
    def guard(original):
        def checked(file, *args, **kwargs):
            if isinstance(file, (str, Path)) and 'truth' in str(file).casefold():
                pytest.fail('Runtime attempted to access benchmark truth')
            return original(file, *args, **kwargs)
        return checked
    monkeypatch.setattr(builtins, 'open', guard(original_builtin))
    monkeypatch.setattr(io, 'open', guard(original_io))
    monkeypatch.setenv('RAKSHA_SECRET', 'measurement-isolation-key')
    RakshaPipeline().run(tmp_path/'data/input', tmp_path/'out')
