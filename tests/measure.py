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
    env = dict(os.environ, RAKSHA_SECRET='measurement-only-fixed-key')
    for seed in range(1, 7):
        profile = 'tune' if seed <= 3 else 'holdout'
        base = root / f'{profile}-{seed}'
        generate(seed, 300, profile, base)
        outputs, exits = [], []
        for attempt in range(2):
            out = base/f'output-{attempt}'
            # Runtime receives only the input subtree; subprocess output is
            # discarded to avoid inspecting holdout examples.
            result = subprocess.run([sys.executable, str(repo/'main.py'), '--input',
                str((base/'input').resolve()), '--output', str(out.resolve())],
                env=env, cwd=repo, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            outputs.append(out)
            exits.append(result.returncode)
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
        metadata = dict(exit_code=max(exits), deterministic=comparable(outputs[0]) == comparable(outputs[1]))
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
