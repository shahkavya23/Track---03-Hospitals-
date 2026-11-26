"""Run a frozen benchmark; holdout emits aggregate scores only."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tests.gen.__main__ import generate
from tests.score import score


def run(root):
    repo = Path(__file__).resolve().parents[1]
    table = []
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
    env = dict(os.environ, RAKSHA_SECRET='measurement-only-fixed-key')
    for seed in range(1, 7):
        profile = 'tune' if seed <= 3 else 'holdout'
        base = root / f'{profile}-{seed}'
        generate(seed, 300, profile, base, surface_variants=60)
        outputs, exits = [], []
        for attempt in range(2):
            out = base/f'output-{attempt}'
            # Runtime receives only the input subtree; subprocess output is
            # discarded to avoid inspecting holdout examples.
            out.mkdir(parents=True, exist_ok=True)
            try:
                result = subprocess.run([sys.executable, '-m', 'tests.guarded_runtime', str(repo/'main.py'), '--input',
                    str((base/'input').resolve()), '--output', str(out.resolve())],
                    env=env, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    timeout=900)
                (out/'runtime.log').write_bytes(result.stdout + result.stderr)
                exit_code = result.returncode
            except subprocess.TimeoutExpired as exc:
                (out/'runtime.log').write_bytes((exc.stdout or b'') + (exc.stderr or b''))
                exit_code = 124
            outputs.append(out)
            exits.append(exit_code)
        def comparable(out):
            content = {}
            for p in sorted(out.rglob('*')):
                if p.is_file():
                    raw = p.read_bytes()
                    if p.name == 'report.json':
                        report = json.loads(raw)
                        report.pop('timing', None)
                        report.pop('resources', None)
                        raw = json.dumps(report, sort_keys=True).encode()
                    content[p.relative_to(out).as_posix()] = raw
            return content
        metadata = dict(exit_code=max(exits), deterministic=comparable(outputs[0]) == comparable(outputs[1]),
                        pipeline_revision=revision, seed=seed, profile=profile)
        (outputs[0]/'measurement.json').write_text(json.dumps(metadata))
        card = score(base/'truth', outputs[0])
        (base/'scorecard.json').write_text(json.dumps(card, sort_keys=True, indent=2))
        row = dict(seed=seed, profile=profile, **card['categories'], total=card['total'])
        table.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)
    (root/'summary.json').write_text(json.dumps(table, indent=2))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    run(parser.parse_args().out.resolve())
