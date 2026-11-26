"""Re-score saved releases; never print holdout contents or examples."""
import argparse
import json
from pathlib import Path
from tests.score import score


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    summary = []
    for seed in range(1, 7):
        profile = 'tune' if seed <= 3 else 'holdout'
        base = args.root/f'{profile}-{seed}'
        card = score(base/'truth', base/'output-0')
        (base/'scorecard-v2.json').write_text(json.dumps(card, sort_keys=True, indent=2)+'\n')
        row = dict(seed=seed, profile=profile, **card['categories'], total=card['total'],
                   canaries=card['canary_count'], report_count_mismatches=len(card['report_count_mismatches']))
        summary.append(row)
        print(json.dumps(row, sort_keys=True))
    (args.root/'summary-v2.json').write_text(json.dumps(summary, indent=2)+'\n')
