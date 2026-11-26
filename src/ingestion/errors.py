"""Safe, PII-free exceptions for the RAKSHA ingestion layer."""

from __future__ import annotations


class InputRootError(Exception):
    """Raised when the root input directory cannot be accessed safely."""


class IngestionQuarantineError(Exception):
    """Raised when a specific input file must be quarantined safely.

    The `reason` must be a generic category/code and MUST NEVER contain raw
    file contents, patient attributes, or original filenames.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
