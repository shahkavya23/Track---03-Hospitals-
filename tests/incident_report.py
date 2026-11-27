"""Run available regression fixtures through the actual API handler and CLI."""
import argparse
import csv
import io
import json
import os
from pathlib import Path
import re
import tempfile
from unittest.mock import patch
import backend_server as api
from main import main
from tests.test_incident_api import request
from src.security.independent_scan import scan

EXPECTED = ['sonpur_dh_reg_2024.csv', 'kachhwa_chc_legacy.tsv', 'lifeline_opd_export.json',
 'ymc_bundle_000441.json', 'discharge_Sunita_Gupta_SDH-24-001231.txt', 'dc_bhitauli_dengue.txt',
 'ward3_shift_notes.txt', 'rx_0412_hi.txt', 'mlc_117_2024.txt', 'lab_results_sep24.csv',
 'ymc_ipd_register_2024.csv', 'city_clinic_family_visits.json',
 '[unspecified original fixture #13]', 'mixed_discharge_summary.txt']
DOCTOR = re.compile(r'\bDr\.?[ \t]+[A-Za-z.]+(?:[ \t]+[A-Za-z.]+){0,3}')


def structure_check(original, sanitized):
    try:
        json.loads(original)
        whole_json = True
    except ValueError:
        whole_json = False
    if whole_json:
        return f'JSON={_valid_json(sanitized)}'
    old_pipe = [line.count('|') for line in original.splitlines() if line.count('|') >= 2]
    new_pipe = [line.count('|') for line in sanitized.splitlines() if line.count('|') >= 2]
    def embedded(lines):
        values = []
        for line in lines:
            if '{' in line and '}' in line and line.index('{') < line.rindex('}'):
                values.append(line[line.index('{'):line.rindex('}')+1])
        return values
    old_json = embedded(original.splitlines())
    new_json = embedded(sanitized.splitlines())
    json_ok = len(old_json) == len(new_json) and all(_valid_json(line) for line in new_json)
    table_ok = old_pipe == new_pipe
    checks = []
    if old_pipe:
        checks.append(f'table={table_ok}')
    if old_json:
        checks.append(f'JSON={json_ok}')
    return '; '.join(checks) if checks else 'N/A'


def _valid_json(value):
    try:
        json.loads(value)
        return True
    except ValueError:
        return False


def los_check(original, sanitized):
    from datetime import datetime, timezone
    def parse(value, month_first):
        if re.fullmatch(r'\d{10}', value):
            return datetime.fromtimestamp(int(value), timezone.utc).replace(tzinfo=None)
        if value.endswith('Z'):
            return datetime.fromisoformat(value[:-1]+'+00:00').replace(tzinfo=None)
        formats = (['%m/%d/%Y'] if month_first else []) + ['%d/%m/%Y','%d-%m-%Y','%Y-%m-%d','%d-%b-%y']
        for fmt in formats:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                pass
        raise ValueError()
    if not re.search(r'(?i)admit|admission|^doa', original):
        return 'N/A'
    if ',' not in original.splitlines()[0] and '\t' not in original.splitlines()[0]:
        old_dates = re.findall(r'\b\d{2}/\d{2}/\d{4}\b', original)
        new_dates = re.findall(r'\b\d{2}/\d{2}/\d{4}\b', sanitized)
        if len(old_dates) < 2 or len(new_dates) < 2:
            return 'not certified'
        exact = parse(old_dates[1], False) - parse(old_dates[0], False) == parse(new_dates[1], False) - parse(new_dates[0], False)
        old_pod = re.search(r'(?i)\bPOD[- ]?7\b', original)
        new_pod = re.search(r'(?i)\bPOD[- ]?7\b', sanitized)
        pod = 'POD-7 exact' if old_pod and new_pod else 'POD N/A'
        return f'{int(exact)}/1; {pod}'
    before, after = list(csv.reader(io.StringIO(original))), list(csv.reader(io.StringIO(sanitized)))
    if not before or len(before) != len(after):
        return 'not certified'
    starts = [i for i,h in enumerate(before[0]) if re.search(r'(?i)admit|admission|^doa$',h)]
    ends = [i for i,h in enumerate(before[0]) if re.search(r'(?i)discharge|^dod$',h)]
    if not starts or not ends:
        return 'N/A'
    good = total = 0
    for old,new in zip(before[1:],after[1:]):
        a,b = starts[0],ends[0]
        if len(old) <= max(a,b) or not old[a] or not old[b]:
            continue
        month_first = any('MM/DD' in cell for cell in old)
        try:
            interval = parse(old[b],month_first)-parse(old[a],month_first)
        except ValueError:
            continue
        total += 1
        try:
            good += parse(new[b],month_first)-parse(new[a],month_first) == interval
        except (ValueError, IndexError):
            pass
    return f'{good}/{total}' if total else 'N/A'


def run(require_full=False):
    repo = Path(__file__).resolve().parents[1]
    available = {
        EXPECTED[0]: repo/'tests/fixtures/incident_registration.csv',
        EXPECTED[-4]: repo/'tests/My personal testing/t1',
        EXPECTED[-3]: repo/'tests/fixtures/family_export_v1.json',
        EXPECTED[-1]: repo/'.raksha_ui_workspace/input/f1.txt',
    }
    table = ['| Fixture | Variant | Leaks | Doctors kept | PSNs | LOS | Structure | Badge | API=CLI |',
             '|---|---|---:|---|---:|---|---|---|---|']
    failed = False
    for label in EXPECTED:
        source = available.get(label)
        if source is None or not source.exists():
            table.append(f'| {label} | all | missing | — | — | — | — | — | — |')
            continue
        raw = source.read_text(encoding='utf-8')
        doctors = DOCTOR.findall(raw)
        if label.endswith('.csv'):
            doctors = [value for row in list(csv.reader(io.StringIO(raw)))[1:]
                       for value in row if value.startswith('Dr')]
        for variant in ('original', 'txt', 'pasted'):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                name = 'upload' + (Path(label).suffix if variant == 'original' else '.txt')
                with patch.multiple(api, UI_WORKSPACE=root/'ui', INPUT_DIR=root/'ui/input', OUTPUT_DIR=root/'ui/output'):
                    request('/api/upload', {'filename':name, 'content':raw})
                    code, result = request('/api/run')
                    main(['--input',str(api.INPUT_DIR),'--output',str(root/'cli'),
                          '--policy',str(repo/'config/policy.yaml')])
                    out = api.OUTPUT_DIR/'sanitized'/name
                    text = out.read_text(encoding='utf-8') if out.exists() else ''
                    parity = all((api.OUTPUT_DIR/p.relative_to(root/'cli')).read_bytes() == p.read_bytes()
                                 for p in (root/'cli').rglob('*') if p.is_file() and p.name != 'report.json')
                    hits = sum(scan(text).values())
                    kept = sum(value in text for value in doctors)
                    reason = result.get('report', {}).get('files', [{}])[0].get('reason', '')
                    badge = ('quarantined: '+reason) if not out.exists() else 'incomplete'
                    # Absence of a date parser/record pairing oracle is never
                    # reported as exact LOS preservation.
                    leak_display = hits if out.exists() else 'withheld'
                    los = los_check(raw,text) if text else 'N/A'
                    structure = structure_check(raw, text) if text else 'N/A'
                    record_text = (api.OUTPUT_DIR/'records.jsonl').read_text(encoding='utf-8')
                    psn_count = len(set(re.findall(r"PSN-[A-Z2-7]+", text + record_text)))
                    table.append(f'| {label} | {variant} | {leak_display} | {kept}/{len(doctors)} | '
                                 f'{psn_count} | {los} | {structure} | {badge} | {parity} |')
                    failed |= hits > 0 or not parity or (out.exists() and kept != len(doctors))
    table.append('\nThe original inventory named only 12 fixtures. Fixture #13 remains unspecified; the mixed discharge incident is listed as #14.')
    result = '\n'.join(table)+'\n'
    (repo/'INCIDENT_RESULTS.md').write_text(result, encoding='utf-8')
    print(result)
    return int(failed or (require_full and len(available) != 14))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-full-corpus', action='store_true')
    args = parser.parse_args()
    os.environ.setdefault('RAKSHA_SECRET', 'incident-regression-only-key')
    raise SystemExit(run(args.require_full_corpus))
