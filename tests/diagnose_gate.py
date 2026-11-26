"""Local category-only quarantine diagnosis; never prints patient values."""
import os
from pathlib import Path
import tempfile
import src.serialization.serializer as serializer
from src.serialization.publish_gate import normalized, validate_candidate
from src.pipeline import RakshaPipeline


def check(source, rendered):
    for record in source.records:
        fields = {f.field_path: f.raw_value for f in record.fields}
        for span in record.detections:
            if str(span.role) != 'direct_pii' or span.is_header_detection:
                continue
            raw = fields.get(span.field_path, '')[span.start:span.end]
            value = normalized(raw)
            if len(value) >= 4 and value in normalized(rendered):
                print(span.category, span.detector_source, 'length', len(raw))
    validate_candidate(source, rendered)


if __name__ == '__main__':
    import sys
    serializer.validate_candidate = check
    os.environ.setdefault('RAKSHA_SECRET', 'local-diagnostic-key')
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root/'input').mkdir()
        (root/'input'/'upload.txt').write_bytes(Path(sys.argv[1]).read_bytes())
        RakshaPipeline().run(root/'input', root/'output')
