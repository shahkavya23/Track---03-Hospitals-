import argparse
import csv
import io
import json
import random
from datetime import date, timedelta
from pathlib import Path
from .templates import TUNE
from .holdout import HOLDOUT


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')


def generate(seed, patients, profile, out):
    rng = random.Random(seed)
    template = TUNE if profile == 'tune' else HOLDOUT
    inp, truth = out / 'input', out / 'truth'
    inp.mkdir(parents=True, exist_ok=True)
    truth.mkdir(parents=True, exist_ok=True)
    entities, records, inventory, protected, intervals = [], [], [], [], []
    rows = [[] for _ in range(3)]
    canaries = [f'Canary{profile.title()}Person{seed}ZXQ']
    for i in range(patients):
        pid = f'p{i:06d}'
        name = f'{rng.choice(template["first"])} {rng.choice(template["last"])}'
        if i == 0:
            name = canaries[0]
        household = i // 4
        phone = str(9000000000 + household + seed * 10000)
        age = rng.randint(1, 89)
        locality = template['villages'][household % 3]
        start = date(2024, 1, 1) + timedelta(days=rng.randrange(250))
        end = start + timedelta(days=rng.randint(0, 14))
        abha = str(91000000000000 + seed * 10000 + i)
        sex = rng.choice(['M', 'F'])
        entities.append(dict(id=pid, name=name, sex=sex, age=age, dob=f'{2024-age}-01-01',
                             household=f'h{household}', phone=phone, ids={'ABHA': abha},
                             locality=locality, district='Synthetic District', state='Synthetic State',
                             pin='560001', dx='Fever', month=start.month, los=(end-start).days))
        for hospital in rng.sample(range(3), rng.randint(2, 3)):
            filename = f'hospital_{hospital}.csv'
            loc = f'row:{len(rows[hospital])}'
            row = [name, str(age), sex, locality, phone, abha,
                   start.strftime(template['date']), end.strftime(template['date']), 'Fever',
                   template['note'].format(name=name, phone=phone)]
            rows[hospital].append(row)
            records.append(dict(file=filename, loc=loc, person=pid, reason=None))
            for value, kind, col in [(name, 'PATIENT', 0), (phone, 'PHONE', 4), (abha, 'ABHA', 5), (locality, 'LOCALITY', 3)]:
                inventory.append(dict(file=filename, loc=loc, value=value, type=kind,
                                      surface='cell', script='Latin', column=col))
            protected.append(dict(file=filename, loc=loc, value='BP 120/80', column=9))
            protected.append(dict(file=filename, loc=loc, value='Dolo 650 mg BD', column=9))
            intervals.append(dict(file=filename, loc=loc, person=pid, columns=[6, 7],
                                  dates=[start.isoformat(), end.isoformat()], format=template['date']))
    statuses = {}
    for hospital, data in enumerate(rows):
        filename = f'hospital_{hospital}.csv'
        buf = io.StringIO(newline='')
        writer = csv.writer(buf, lineterminator='\n')
        writer.writerow(template['headers'])
        writer.writerows(data)
        (inp / filename).write_text(buf.getvalue(), encoding='utf-8')
        statuses[filename] = 'sanitized'
    for filename, content in [('broken.json', b'{'), ('image.jpg', b'\xff\xd8\xff'),
                               ('archive.zip', b'PK\x03\x04'), ('empty.txt', b'')]:
        (inp / filename).write_bytes(content)
        statuses[filename] = 'quarantined'
    write_json(truth / 'entities.json', entities)
    write_json(truth / 'file_status.json', statuses)
    write_json(truth / 'canaries.json', canaries)
    write_json(truth / 'manifest.json', dict(seed=seed, patients=patients, profile=profile,
        coverage=['namesakes', 'shared_household_phone', 'cross_hospital', 'csv', 'quarantine_bait'],
        unsupported=['twins', 'newborns', 'nested_json', 'fhir', 'multiscript', 'legacy_encodings']))
    for name, values in [('records', records), ('pii_inventory', inventory), ('protected', protected), ('intervals', intervals)]:
        (truth / (name + '.jsonl')).write_text(''.join(json.dumps(v, ensure_ascii=False, sort_keys=True)+'\n' for v in values), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--patients', type=int, default=300)
    parser.add_argument('--profile', choices=['tune', 'holdout'], required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    generate(args.seed, args.patients, args.profile, args.out)
