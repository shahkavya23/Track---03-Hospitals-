"""Format-specific parsers returning normalized PatientRecords."""

from .fhir_parser import parse_fhir_document
from .json_parser import parse_json_document
from .tabular import parse_tabular_document
from .text_parser import parse_text_document

__all__ = [
    "parse_fhir_document",
    "parse_json_document",
    "parse_tabular_document",
    "parse_text_document",
]
