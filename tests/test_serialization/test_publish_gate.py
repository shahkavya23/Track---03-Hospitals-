import pytest
from src.contracts import DetectionSpan, FieldNode, PatientRecord, SourceFile, FileFormat, ParseStatus, SpanRole
from src.serialization.publish_gate import validate_candidate


def test_detected_identifier_cannot_pass_publication():
    record = PatientRecord('r', 's', 'doc', 'Phone 9876543210',
                           fields=[FieldNode('doc', 'Phone 9876543210', '', False)])
    record.detections = [DetectionSpan('r', 'doc', 6, 16, 'PHONE', SpanRole.DIRECT_PII, 1, 'test')]
    source = SourceFile('s', '0'*64, 'a.txt', 'sanitized/a.txt', FileFormat.TEXT,
                        'utf-8', ParseStatus.PARSED, records=[record])
    with pytest.raises(ValueError, match='residual identifiers'):
        validate_candidate(source, 'Phone 98765 43210')
    validate_candidate(source, 'Phone [PHONE]')
