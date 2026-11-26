"""Clinical integrity protection layer — owned by Member 2."""

from __future__ import annotations

from .conditions import (
    detect_condition_and_procedure_spans,
    is_clinical_complaint_phrase,
)
from .guard import ClinicalIntegrityGuard, HARD_DIRECT_PII_CATEGORIES, STRUCTURED_CLINICAL_HEADERS
from .medications import ClinicalMatch, detect_medication_spans
from .vitals_labs import detect_vital_and_lab_spans

__all__ = [
    "ClinicalIntegrityGuard",
    "ClinicalMatch",
    "HARD_DIRECT_PII_CATEGORIES",
    "STRUCTURED_CLINICAL_HEADERS",
    "detect_condition_and_procedure_spans",
    "detect_medication_spans",
    "detect_vital_and_lab_spans",
    "is_clinical_complaint_phrase",
]
