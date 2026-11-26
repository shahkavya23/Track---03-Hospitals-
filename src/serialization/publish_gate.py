"""In-memory rendering and fail-closed publication checks."""
import io
import json
import re
import unicodedata

from src.contracts import FileFormat, SpanRole


class MemoryTarget:
    def __init__(self):
        self.value = ''

    def write_text(self, value, **kwargs):
        self.value = value

    def open(self, *args, **kwargs):
        target = self

        class Buffer(io.StringIO):
            def close(self):
                target.value = self.getvalue()
                super().close()
        return Buffer(newline='')


def normalized(value):
    value = unicodedata.normalize('NFKC', value).casefold()
    return ''.join(str(unicodedata.digit(c)) if c.isdigit() else c
                   for c in value if not c.isspace() and c not in '-\u200b\u200c\u200d')


def residual_hits(source, rendered):
    """Detected direct identifiers stay in memory; never expose values in errors."""
    registry = set()
    for record in source.records:
        fields = {f.field_path: f.raw_value for f in record.fields}
        for span in record.detections:
            if span.role != SpanRole.DIRECT_PII or span.is_header_detection:
                continue
            raw = fields.get(span.field_path, '')[span.start:span.end]
            if any(d.field_path == span.field_path and d.start is None and
                   d.replacement_value == fields.get(span.field_path) for d in record.privacy_decisions):
                continue
            value = normalized(raw)
            if len(value) >= 4 and value not in {'self', 'unknown'}:
                registry.add(value)
    searchable = normalized(rendered)
    return sum(value in searchable for value in sorted(registry))


def validate_candidate(source, rendered):
    if source.format in (FileFormat.JSON, FileFormat.FHIR_R4):
        json.loads(rendered)
    if re.search(r'UNRESOLVED|CONFLICTING_IDENTITY_EVIDENCE', rendered):
        raise ValueError('unsafe output')
    hits = residual_hits(source, rendered)
    if hits:
        raise ValueError('residual identifiers')
    searchable = rendered
    if source.format == FileFormat.FHIR_R4:
        from .validator import _collect_fhir_searchable_text
        searchable = _collect_fhir_searchable_text(json.loads(rendered), rendered)
    for record in source.records:
        for value in record.clinical_attributes:
            if value and value not in searchable:
                from .validator import _privacy_safe_clinical_form
                if _privacy_safe_clinical_form(value) not in searchable:
                    raise ValueError('clinical integrity')
