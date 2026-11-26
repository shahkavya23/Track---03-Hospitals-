import builtins
import hashlib
import io
import json
from pathlib import Path
import shutil
import pytest
from tests.gen.__main__ import generate
from tests.score import score


def test_holdout_templates_frozen():
    path = Path(__file__).parent / 'gen/holdout.py'
    assert hashlib.sha256(path.read_bytes()).hexdigest() == 'f01fec78f36ef8316df7b225a905ea2b84e1633066f703bc97e1ac687b161a8b'


def test_generator_deterministic(tmp_path):
    for name in ('a', 'b'):
        generate(1, 50, 'tune', tmp_path/name)
    for path in sorted((tmp_path/'a').rglob('*')):
        if path.is_file():
            assert path.read_bytes() == (tmp_path/'b'/path.relative_to(tmp_path/'a')).read_bytes()


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
