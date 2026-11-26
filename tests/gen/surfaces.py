"""Metadata probes: same trap categories, profile-specific identities and wording."""
import base64
import csv
import io
import json


def add_surfaces(inp, template, profile, seed, count, inventory, statuses):
    surfaces = ['header', 'key', 'filename', 'attachment', 'free text', 'FHIR narrative', 'cell']
    encodings = ['utf-8', 'utf-8-sig', 'utf-16', 'utf-16-le', 'utf-16-be', 'cp1252']
    for idx in range(count):
        surface = surfaces[idx % len(surfaces)]
        name = f'{template["first"][idx % len(template["first"])]} {profile.title()}Probe{seed}X{idx}'
        phone = str(9800000000 + seed * 10000 + idx)
        digits = ['0123456789', '०१२३४५६७८९', '۰۱۲۳۴۵۶۷۸۹', '੦੧੨੩੪੫੬੭੮੯'][idx % 4]
        encoded_phone = phone.translate(str.maketrans('0123456789', digits))
        script = ['Latin', 'Devanagari', 'Urdu', 'Gurmukhi'][idx % 4]
        filename = f'probe_{idx:03d}.txt'
        text = ('Operator: '+name+'. Phone: '+encoded_phone if profile == 'tune'
                else 'Export custodian: '+name+'; telephone '+encoded_phone)
        if surface == 'header':
            filename = f'probe_{idx:03d}.csv'
            buf = io.StringIO(newline='')
            writer = csv.writer(buf, lineterminator='\n')
            writer.writerow(['notes verified by '+name+' '+encoded_phone])
            writer.writerow(['No clinical record'])
            text = buf.getvalue()
        elif surface == 'key':
            filename = f'probe_{idx:03d}.json'
            text = json.dumps({name: {'operator_contact': encoded_phone}}, ensure_ascii=False)
        elif surface == 'filename':
            filename = f'probe_{name.replace(" ", "_")}_{idx}.txt'
        elif surface == 'attachment':
            filename = f'probe_{idx:03d}.json'
            text = json.dumps({'attachment': {'contentType': 'text/plain',
                'data': base64.b64encode(text.encode()).decode()}})
        elif surface == 'FHIR narrative':
            filename = f'probe_{idx:03d}.json'
            text = json.dumps({'resourceType': 'DocumentReference', 'status': 'current',
                'text': {'status': 'generated', 'div': '<div xmlns="http://www.w3.org/1999/xhtml">'+text+'</div>'},
                'content': [{'attachment': {'contentType': 'text/plain', 'data': base64.b64encode(text.encode()).decode()}}]}, ensure_ascii=False)
        elif surface == 'cell':
            filename = f'probe_{idx:03d}.tsv'
            text = 'operator\tphone\n'+name+'\t'+encoded_phone+'\n'
        encoding = encodings[idx % len(encodings)]
        if encoding == 'cp1252' and not text.isascii():
            encoding = 'utf-8'
        (inp/filename).write_bytes(text.encode(encoding))
        statuses[filename] = 'sanitized'
        for value, kind, value_script in [(name, 'STAFF', 'Latin'), (encoded_phone, 'PHONE', script)]:
            inventory.append(dict(file=filename, loc='metadata', value=value, type=kind,
                                  surface=surface, script=value_script))
