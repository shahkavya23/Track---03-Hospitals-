"""Independent truth-based measurement. Runtime code must never import this module."""
import argparse
import base64
from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
from itertools import combinations
import json
from pathlib import Path
import re
import unicodedata


def norm(value):
    value = value.translate(str.maketrans({'А':'A','В':'B','С':'C','Е':'E','Н':'H','К':'K',
        'М':'M','О':'O','Р':'P','Т':'T','Х':'X','а':'a','с':'c','е':'e','о':'o','р':'p','х':'x',
        'Α':'A','Β':'B','Ε':'E','Ο':'O','Ρ':'P','Χ':'X'}))
    return ''.join(str(unicodedata.digit(c)) if c.isdigit() else c for c in
                   unicodedata.normalize('NFKC', value).casefold()
                   if not c.isspace() and c not in '-\u200b\u200c\u200d')


def lines(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()] if path.exists() else []


def ratio(a, b):
    return a / b if b else 0.0


def searchable_artifact(path):
    text = path.read_text(encoding='utf-8', errors='replace')
    if path.suffix.lower() != '.json':
        return text
    try:
        payload = json.loads(text)
    except ValueError:
        return text
    chunks = [text]
    stack = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, value in item.items():
                chunks.append(key)
                if key.casefold() in {'data', 'bytes_b64', 'attachment_base64'} and isinstance(value, str):
                    try:
                        chunks.append(base64.b64decode(value, validate=True).decode('utf-8'))
                    except (ValueError, UnicodeError):
                        pass
                stack.append(value)
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, str):
            chunks.append(item)
    return '\n'.join(chunks)


def score(truth, output):
    records = lines(truth / 'records.jsonl')
    pii = lines(truth / 'pii_inventory.jsonl')
    protected = lines(truth / 'protected.jsonl')
    entities = {p['id']: p for p in json.loads((truth / 'entities.json').read_text())}
    statuses = json.loads((truth / 'file_status.json').read_text())
    canaries = json.loads((truth / 'canaries.json').read_text())
    paths = sorted(p for p in output.rglob('*') if p.is_file() and p.name != 'scorecard.json')
    all_text = '\n'.join(p.relative_to(output).as_posix() + '\n' + searchable_artifact(p) for p in paths)
    searchable = norm(all_text)
    rendered, parse_errors = {}, 0
    for filename in statuses:
        path = output / 'sanitized' / filename
        if path.exists() and path.suffix == '.csv':
            try:
                with path.open(encoding='utf-8', newline='') as handle:
                    rendered[filename] = list(csv.reader(handle))
            except (ValueError, UnicodeError):
                parse_errors += 1

    def row_at(item):
        try:
            return rendered[item['file']][int(item['loc'].split(':')[1])+1]
        except (KeyError, IndexError, ValueError):
            return []

    breakdown = defaultdict(lambda: [0, 0])
    leaks = []
    locality_support = Counter(p['locality'] for p in entities.values())
    excluded_qi = 0
    scored_pii = []
    for item in pii:
        # A k-supported locality is permitted utility, not a direct-PII leak.
        # Count distinct truth persons, never repeated hospital appearances.
        if item['type'] == 'LOCALITY' and locality_support[item['value']] >= 5:
            excluded_qi += 1
            continue
        scored_pii.append(item)
        hit = norm(item['value']) in searchable
        for group in ('type', 'surface', 'script'):
            key = group + ':' + item[group]
            breakdown[key][0] += not hit
            breakdown[key][1] += 1
        if hit:
            leaks.append({k: item[k] for k in ('file', 'loc', 'type', 'surface', 'script')})
    detection = 100 * ratio(len(scored_pii)-len(leaks), len(scored_pii))
    # Missing releases do not earn detection credit for deleting all records.
    availability = ratio(sum(bool(row_at(r)) for r in records), len(records))
    detection *= availability
    survival = ratio(sum(item['value'] in ' '.join(row_at(item)) for item in protected), len(protected))
    intervals = lines(truth / 'intervals.jsonl')
    interval_ok, date_tokens = 0, 0
    for item in intervals:
        row = row_at(item)
        try:
            a, b = [row[c] for c in item['columns']]
            date_tokens += (a == '[DATE]') + (b == '[DATE]')
            before = [datetime.fromisoformat(v) for v in item['dates']]
            after = [datetime.strptime(v, item['format']) for v in (a, b)]
            interval_ok += after[1]-after[0] == before[1]-before[0]
        except (IndexError, ValueError):
            pass
    ages_ok = 0
    released_profiles = []
    for item in records:
        row = row_at(item)
        entity = entities.get(item['person'])
        if len(row) < 10 or entity is None:
            continue
        age = row[1]
        band = re.fullmatch(r'(\d+)-(\d+)', age)
        ages_ok += bool((band and int(band[1]) <= entity['age'] <= int(band[2])) or
                        (age == '90+' and entity['age'] >= 90) or (age == '<1' and entity['age'] < 1))
        released_profiles.append((item['person'], row))
    medical = 100 * (survival + ratio(interval_ok, len(intervals)) + ratio(ages_ok, len(records))) / 3
    predicted = {(r['file'].removeprefix('sanitized/'), r['loc']): r.get('patient')
                 for r in lines(output / 'records.jsonl')}
    tp = fp = fn = 0
    for left, right in combinations(records, 2):
        a = predicted.get((left['file'], left['loc']))
        b = predicted.get((right['file'], right['loc']))
        same = left['person'] is not None and left['person'] == right['person']
        match = bool(a and b and a == b)
        tp += same and match
        fp += not same and match
        fn += same and not match
    precision, recall = ratio(tp, tp+fp), ratio(tp, tp+fn)
    identity = 100 * ratio(tp, tp + 3*fp + fn)
    # Attack matches released generalisations to the external truth register.
    attack = {}
    for pid, row in released_profiles:
        candidates = []
        for other in entities.values():
            age = re.fullmatch(r'(\d+)-(\d+)', row[1])
            age_match = int(age[1]) <= other['age'] <= int(age[2]) if age else row[1] == str(other['age'])
            location_match = row[3] in {'[ADDRESS]', other['locality'], other['district'], other['state']} or row[3].endswith('XXX region')
            if age_match and row[2] == other['sex'] and location_match and row[8] == other['dx']:
                candidates.append(other['id'])
        attack.setdefault(pid, len(candidates))
    unique = ratio(sum(k == 1 for k in attack.values()), len(entities))
    small = ratio(sum(0 < k < 5 for k in attack.values()), len(entities))
    raw_identity = ratio(sum(norm(p['name']) in searchable for p in entities.values()), len(entities))
    privacy = 100 * (1 - max(unique, raw_identity))
    expected_shapes = Counter(r['file'] for r in records)
    valid = sum(f in rendered and len(rendered[f]) == n+1 and all(len(r)==10 for r in rendered[f])
                for f, n in expected_shapes.items())
    validity = 100 * ratio(valid, len(expected_shapes))
    report_path = output / 'report.json'
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    file_reports = {entry['input_sha256']: entry for entry in report.get('files', [])}
    input_root = truth.parent / 'input'
    quarantine_ok = 0
    raw_copies = []
    for filename, expected in statuses.items():
        original = input_root / filename
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        entry = file_reports.get(digest, {})
        path = output / entry.get('output', '') if entry.get('output') else None
        quarantine_ok += bool(entry.get('status') == expected and (
            (expected == 'quarantined' and path is None and not (output/'sanitized'/filename).exists())
            or (expected == 'sanitized' and path is not None and path.is_file())))
        candidate = output/'sanitized'/filename
        if expected == 'sanitized' and candidate.is_file() and candidate.read_bytes() == original.read_bytes():
            raw_copies.append(filename)
    declared = report.get('counts', {})
    actual_lines = lines(output/'records.jsonl')
    count_checks = {
        'files_total': len(statuses),
        'files_sanitized': sum(entry.get('status') == 'sanitized' for entry in file_reports.values()),
        'files_quarantined': sum(entry.get('status') == 'quarantined' for entry in file_reports.values()),
        'records_processed': len(actual_lines),
        'records_linked': sum(bool(row.get('patient')) for row in actual_lines),
    }
    count_mismatches = [key for key, value in count_checks.items() if declared.get(key) != value]
    validity = (validity + 100*ratio(quarantine_ok,len(statuses)) +
                (100 if not count_mismatches else 0)) / 3
    run = json.loads((output / 'measurement.json').read_text()) if (output / 'measurement.json').exists() else {}
    within_limits = (report.get('timing', {}).get('seconds', float('inf')) <= 900 and
                     report.get('resources', {}).get('peak_rss_mb', float('inf')) <= 4096)
    reliability = 100.0 if run.get('exit_code') == 0 and run.get('deterministic') is True and within_limits else 0.0
    canary_hits = sorted({value for value in canaries if norm(value) in searchable})
    penalty = 20 * len(canary_hits) + 10 * len(raw_copies)
    categories = dict(privacy=privacy, pii_detection=detection, medical=medical,
                      identity=identity, validity=validity, speed_reliability=reliability)
    return dict(score_version='csv-plus-metadata-v2', categories={k: round(v, 3) for k,v in categories.items()},
                total=round(max(0, sum(categories.values())/6-penalty), 3),
                canary_count=len(canary_hits), canary_penalty=20*len(canary_hits),
                penalty_breakdown={'canary': 20*len(canary_hits), 'raw_copy': 10*len(raw_copies)},
                raw_copy_count=len(raw_copies), quarantine_accuracy=ratio(quarantine_ok,len(statuses)),
                report_count_mismatches=count_mismatches, permitted_locality_observations=excluded_qi,
                pii_recall={k: ratio(a,b) for k,(a,b) in sorted(breakdown.items())},
                protected_recall=survival, interval_exactness=ratio(interval_ok,len(intervals)),
                age_truthfulness=ratio(ages_ok,len(records)), absolute_date_token_rate=ratio(date_tokens,2*len(intervals)),
                pairwise_precision=precision, pairwise_recall=recall,
                pairwise_f1=ratio(2*precision*recall,precision+recall), wrong_merges=fp, missed_links=fn,
                null_or_missing_rate=ratio(sum(not predicted.get((r['file'],r['loc'])) for r in records),len(records)),
                attack_unique_pct=100*unique, attack_k_under_5_pct=100*small,
                tune_failures=leaks[:10] if json.loads((truth/'manifest.json').read_text())['profile']=='tune' else [],
                runtime=report.get('timing'), resources=report.get('resources'),
                limitations=['CSV-only structural and interval scoring', 'FHIR schema validator not installed',
                'attack omits admission month and LOS until independent date decoding is available',
                'shift-inference, applied-event validation and null reasons unimplemented'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--truth', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    card = score(args.truth, args.output)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'scorecard.json').write_text(json.dumps(card, sort_keys=True, indent=2)+'\n')
    for name, value in card['categories'].items():
        print(f'{name:24} {value:8.3f}')
    print(f'total                    {card["total"]:8.3f}')
