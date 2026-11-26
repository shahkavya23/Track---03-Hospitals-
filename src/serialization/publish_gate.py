"""In-memory rendering and fail-closed publication checks."""
import io
import base64
from collections import Counter
from dataclasses import dataclass
import json
import re
import unicodedata

from src.contracts import FileFormat, SpanRole
from src.security.independent_scan import TOKENS, scan, scan_findings

KINSHIP_WORDS = frozenset({
    'mother', 'father', 'sister', 'brother', 'wife', 'husband', 'guardian',
    'nani', 'nana', 'dadi', 'dada', 'maa', 'pita', 'mata', 'amma', 'abbu',
})


def _contains_generic_kinship(value):
    words = set(re.findall(r"[A-Za-z]+", value.casefold()))
    return bool(words & KINSHIP_WORDS)


@dataclass(frozen=True, slots=True)
class LateRedactionResult:
    value: str
    iterations: int
    replacements: int
    late_categories: dict[str, int]
    remaining: dict[str, int]


def _preserve_line_breaks(raw: str, replacement: str) -> str:
    return replacement + ''.join(re.findall(r'\r\n|\r|\n', raw))


def _redact_embedded_json_lines(value: str) -> tuple[str, int]:
    """Sanitize standalone JSON lines in mixed prose without treating the file as JSON."""
    sensitive = re.compile(r'(?i)(?:patient|person|relative|guardian|speaker|name|phone|mobile|aadhaar|address|upi|account)')
    doctor = re.compile(r'(?i)(?:doctor|clinician|consultant|practitioner)')
    replacements = 0

    def walk(item, key=''):
        nonlocal replacements
        if isinstance(item, dict):
            return {k: walk(v, str(k)) for k, v in item.items()}
        if isinstance(item, list):
            return [walk(v, key) for v in item]
        if isinstance(item, str) and sensitive.search(key) and not doctor.search(key):
            token = '[PHONE]' if re.search(r'(?i)phone|mobile', key) else '[ADDRESS]' if re.search(r'(?i)address', key) else '[PATIENT]'
            replacements += item != token
            return token
        return item

    output: list[str] = []
    for line in value.splitlines(keepends=True):
        ending = line[len(line.rstrip('\r\n')):]
        body = line[:-len(ending)] if ending else line
        stripped = body.strip()
        if stripped.startswith(('{', '[')) and stripped.endswith(('}', ']')):
            try:
                parsed = json.loads(stripped)
            except (ValueError, TypeError):
                output.append(line)
                continue
            leading = body[:len(body)-len(body.lstrip())]
            output.append(leading + json.dumps(walk(parsed), ensure_ascii=False, separators=(',', ':')) + ending)
        else:
            output.append(line)
    return ''.join(output), replacements


def _redact_base64(value: str) -> tuple[str, int]:
    pattern = re.compile(r'(?<![A-Za-z0-9+/=])(?:[A-Za-z0-9+/]{4}){6,}(?:==|=)?(?![A-Za-z0-9+/=])')
    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        try:
            payload = base64.b64decode(match.group(0), validate=True)
        except (ValueError, TypeError):
            return match.group(0)
        try:
            decoded = payload.decode('utf-8')
        except UnicodeError:
            count += 1
            return '[REDACTED]'
        if not decoded or sum(ch.isprintable() or ch in '\r\n\t' for ch in decoded) / len(decoded) < .9:
            count += 1
            return '[REDACTED]'
        findings = scan_findings(decoded)
        if not findings:
            return match.group(0)
        for finding in reversed(findings):
            decoded = decoded[:finding.start] + _preserve_line_breaks(
                decoded[finding.start:finding.end], finding.replacement
            ) + decoded[finding.end:]
        count += len(findings)
        return base64.b64encode(decoded.encode('utf-8')).decode('ascii')

    return pattern.sub(replace, value), count


def reredact_candidate(rendered: str, max_iterations: int = 3) -> LateRedactionResult:
    """Use only independent findings for bounded late redaction before quarantine."""
    value, structured_count = _redact_embedded_json_lines(rendered)
    total = structured_count
    late = Counter()
    iterations = 0
    for attempt in range(1, max_iterations + 1):
        value, base64_count = _redact_base64(value)
        total += base64_count
        findings = scan_findings(value)
        unknowns = list(re.finditer(r'\[([A-Z][A-Z_-]*)\]', value))
        unknowns = [m for m in unknowns if m.group(1) not in TOKENS]
        if not findings and not unknowns:
            break
        iterations = attempt
        for finding in findings:
            late[finding.category] += 1
        edits = [(f.start, f.end, f.replacement) for f in findings]
        edits.extend((m.start(), m.end(), '[REDACTED]') for m in unknowns)
        selected = []
        for start, end, replacement in sorted(edits, key=lambda item: (item[0], -(item[1]-item[0]))):
            if selected and start < selected[-1][1]:
                continue
            selected.append((start, end, replacement))
        for start, end, replacement in reversed(selected):
            value = value[:start] + _preserve_line_breaks(value[start:end], replacement) + value[end:]
        total += len(selected)
    return LateRedactionResult(value, iterations, total, dict(sorted(late.items())), scan(value))


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


_DOCTOR_SPAN_RE = re.compile(
    r"(?i)(?:\bDr\.?|\bDoctor|डॉ\.?|डॉक्टर|ڈاکٹر)[ \t]+"
    r"(?:[A-Z][A-Za-z'’.-]{1,24}|[A-Z]\.|[\u0900-\u097f]{2,24}|[\u0600-\u06ff]{2,24})"
    r"(?:[ \t]+(?:[A-Z][A-Za-z'’.-]{1,24}|[A-Z]\.|[\u0900-\u097f]{2,24}|[\u0600-\u06ff]{2,24})){0,3}"
)


def _inside_doctor_span(text: str, start: int, end: int) -> bool:
    return any(start < m.end() and m.start() < end for m in _DOCTOR_SPAN_RE.finditer(text))


def residual_hits(source, rendered):
    """Detected direct identifiers stay in memory; never expose values in errors."""
    registry = set()
    protected = {
        normalized(value) for record in source.records
        for value in record.clinical_attributes if value
    }
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
            if span.category == 'RELATIVE_NAME' and _contains_generic_kinship(raw):
                continue
            if len(value) >= 4 and value not in {'self', 'unknown'} | KINSHIP_WORDS and value not in protected:
                registry.add(value)
    # Protected doctor mentions are allowed context, not residual patient
    # mentions when a namesake shares their first or family name.
    searchable = normalized(_DOCTOR_SPAN_RE.sub("", rendered))
    return sum(value in searchable for value in sorted(registry))


def reredact_registry(source, rendered):
    """Late exact-value sweep after the independent pass; clinician contexts stay protected."""
    token_for = {
        'PATIENT_NAME': '[PATIENT]', 'PERSON_NAME': '[PERSON]',
        'RELATIVE_NAME': '[RELATIVE]', 'PHONE': '[PHONE]', 'MOBILE': '[PHONE]',
        'AADHAAR': '[AADHAAR]', 'PAN': '[PAN]', 'ABHA': '[ABHA]',
        'EMAIL': '[EMAIL]', 'ADDRESS': '[ADDRESS]', 'VILLAGE': '[ADDRESS]',
        'LOCATION': '[ADDRESS]', 'SCHOOL': '[SCHOOL]', 'OCCUPATION': '[OCCUPATION]',
    }
    values = []
    protected = {
        normalized(value) for record in source.records
        for value in record.clinical_attributes if value
    }
    for record in source.records:
        fields = {field.field_path: field.raw_value for field in record.fields}
        for span in record.detections:
            if span.role != SpanRole.DIRECT_PII or span.is_header_detection:
                continue
            raw = fields.get(span.field_path, '')[span.start:span.end]
            if span.category == 'RELATIVE_NAME' and _contains_generic_kinship(raw):
                continue
            if (len(normalized(raw)) < 4 or normalized(raw) in protected or
                    normalized(raw) in KINSHIP_WORDS or raw.startswith('[')):
                continue
            values.append((raw, token_for.get(span.category, '[REDACTED]')))
    count = 0
    for raw, replacement in sorted(set(values), key=lambda item: (-len(item[0]), item[0].casefold(), item[1])):
        pattern = re.compile(re.escape(raw), re.IGNORECASE)

        def replace(match):
            nonlocal count
            if _inside_doctor_span(rendered, match.start(), match.end()):
                return match.group(0)
            count += 1
            return _preserve_line_breaks(match.group(0), replacement)

        rendered = pattern.sub(replace, rendered)
    return rendered, count


def validate_candidate(source, rendered):
    if source.format == FileFormat.JSONL:
        for line in rendered.splitlines():
            if line.strip():
                json.loads(line)
    findings = scan(rendered)
    if findings:
        raise ValueError('independent residual identifiers')
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
