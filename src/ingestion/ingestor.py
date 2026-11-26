# Purpose: Main ingestion coordinator loading policy.yaml, running security/encoding/format gates, and building SourceFiles.
"""Universal, security-hardened file ingestor for RAKSHA (Member 1)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence

import yaml

from src.contracts import FileFormat, ParseStatus, PatientRecord, SourceFile

from .encoding import decode_bytes_to_utf8
from .errors import IngestionQuarantineError
from .format_detect import DEFAULT_SUPPORTED_EXTENSIONS, detect_format
from .parsers import (
    parse_fhir_document,
    parse_json_document,
    parse_tabular_document,
    parse_text_document,
)
from .security import discover_input_entries


@dataclass(frozen=True, slots=True)
class IngestionConfig:
    """Runtime parameters controlling safe ingestion and quarantine limits."""

    max_file_bytes: int = 52_428_800
    max_json_depth: int = 64
    empty_file_action: str = "quarantine"
    supported_extensions: tuple[str, ...] = DEFAULT_SUPPORTED_EXTENSIONS
    csv_allowed_delimiters: tuple[str, ...] = (",", ";", "|")
    encoding_fallbacks: tuple[str, ...] = ("cp1252", "iso-8859-1")

    @classmethod
    def from_policy_file(cls, policy_path: Path) -> "IngestionConfig":
        """Load ingestion settings from config/policy.yaml safely."""
        with policy_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        section = raw.get("ingestion") or {}
        return cls(
            max_file_bytes=int(section.get("max_file_bytes", 52_428_800)),
            max_json_depth=int(section.get("max_json_depth", 64)),
            empty_file_action=str(section.get("empty_file_action", "quarantine")),
            supported_extensions=tuple(
                str(ext).lower()
                for ext in section.get("supported_extensions", DEFAULT_SUPPORTED_EXTENSIONS)
            ),
            csv_allowed_delimiters=tuple(
                str(delim) for delim in section.get("csv_allowed_delimiters", (",", ";", "|"))
            ),
            encoding_fallbacks=tuple(
                str(enc) for enc in section.get("encoding_fallbacks", ("cp1252", "iso-8859-1"))
            ),
        )


class UniversalIngestor:
    """Discovers, validates, decodes, and parses multi-format healthcare inputs."""

    def __init__(self, config: IngestionConfig | None = None) -> None:
        self.config = config or IngestionConfig()

    def ingest_directory(self, input_dir: Path) -> list[SourceFile]:
        """Ingest all entries under input_dir deterministically without modifying inputs."""
        entries = discover_input_entries(
            input_root=input_dir,
            max_file_bytes=self.config.max_file_bytes,
            empty_file_action=self.config.empty_file_action,
        )

        record_counter = 0

        def next_record_ref() -> str:
            nonlocal record_counter
            record_counter += 1
            return f"rec_{record_counter:08d}"

        source_files: list[SourceFile] = []
        for idx, entry in enumerate(entries, start=1):
            source_ref = f"src_{idx:06d}"
            if entry.quarantine_reason is not None or entry.abs_path is None:
                source_files.append(
                    SourceFile(
                        source_ref=source_ref,
                        source_sha256=entry.sha256,
                        relative_path=entry.relative_posix,
                        sanitized_relative_path=None,
                        format=FileFormat.UNSUPPORTED,
                        encoding="unknown",
                        parse_status=ParseStatus.QUARANTINED,
                        quarantine_reason=entry.quarantine_reason or "quarantined input",
                        records=[],
                    )
                )
                continue

            source_files.append(
                self._ingest_single_file(
                    abs_path=entry.abs_path,
                    relative_posix=entry.relative_posix,
                    sha256=entry.sha256,
                    source_ref=source_ref,
                    next_record_ref=next_record_ref,
                )
            )

        return source_files

    def _ingest_single_file(
        self,
        abs_path: Path,
        relative_posix: str,
        sha256: str,
        source_ref: str,
        next_record_ref,
    ) -> SourceFile:
        detected_format = FileFormat.UNSUPPORTED
        detected_encoding = "unknown"


        try:
            raw_bytes = abs_path.read_bytes()
        except OSError:
            return self._quarantined_source(
                source_ref=source_ref,
                sha256=sha256,
                relative_posix=relative_posix,
                file_format=detected_format,
                encoding=detected_encoding,
                reason="unreadable file",
            )

        try:
            decoded = decode_bytes_to_utf8(raw_bytes, fallbacks=self.config.encoding_fallbacks)
            detected_encoding = decoded.encoding
            detected_format, parsed_json = detect_format(
                relative_posix=relative_posix,
                text=decoded.text,
                supported_extensions=self.config.supported_extensions,
                max_json_depth=self.config.max_json_depth,
            )

            records: list[PatientRecord]
            if detected_format in (FileFormat.CSV, FileFormat.TSV):
                records = parse_tabular_document(
                    text=decoded.text,
                    source_ref=source_ref,
                    file_format=detected_format,
                    next_record_ref=next_record_ref,
                    allowed_delimiters=self.config.csv_allowed_delimiters,
                )
            elif detected_format in (FileFormat.JSON, FileFormat.JSONL):
                records = parse_json_document(
                    parsed_payload=parsed_json,
                    source_ref=source_ref,
                    next_record_ref=next_record_ref,
                )
            elif detected_format == FileFormat.FHIR_R4:
                records = parse_fhir_document(
                    parsed_payload=parsed_json,
                    source_ref=source_ref,
                    next_record_ref=next_record_ref,
                )
            elif detected_format == FileFormat.TEXT:
                records = parse_text_document(
                    text=decoded.text,
                    source_ref=source_ref,
                    next_record_ref=next_record_ref,
                )
            else:
                raise IngestionQuarantineError("unsupported format")

        except IngestionQuarantineError as exc:
            return self._quarantined_source(
                source_ref=source_ref,
                sha256=sha256,
                relative_posix=relative_posix,
                file_format=detected_format,
                encoding=detected_encoding,
                reason=exc.reason,
            )

        return SourceFile(
            source_ref=source_ref,
            source_sha256=sha256,
            relative_path=relative_posix,
            sanitized_relative_path=f"sanitized/{relative_posix}",
            format=detected_format,
            encoding=detected_encoding,
            parse_status=ParseStatus.PARSED,
            quarantine_reason=None,
            records=records,
        )

    @staticmethod
    def _quarantined_source(
        source_ref: str,
        sha256: str,
        relative_posix: str,
        file_format: FileFormat,
        encoding: str,
        reason: str,
    ) -> SourceFile:
        return SourceFile(
            source_ref=source_ref,
            source_sha256=sha256,
            relative_path=relative_posix,
            sanitized_relative_path=None,
            format=file_format,
            encoding=encoding,
            parse_status=ParseStatus.QUARANTINED,
            quarantine_reason=reason,
            records=[],
        )
