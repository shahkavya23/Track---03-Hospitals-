"""Bounded recursive scans for planted canaries, identifiers, and secrets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class SecurityScanError(RuntimeError):
    """Safe exception that never includes the sensitive value or filename."""


@dataclass(frozen=True, slots=True)
class LeakageScanResult:
    files_scanned: int
    content_findings: int
    filename_findings: int
    symlink_findings: int

    @property
    def total_findings(self) -> int:
        return self.content_findings + self.filename_findings + self.symlink_findings


def _contains_sensitive(data: bytes, needles: Sequence[bytes]) -> bool:
    return any(needle in data for needle in needles)


def scan_for_leaks(
    output_root: Path,
    sensitive_values: Sequence[str | bytes],
    *,
    chunk_size: int = 64 * 1024,
) -> LeakageScanResult:
    """Scan output recursively without following symlinks or reporting raw values."""

    if chunk_size < 1024:
        raise ValueError("Leakage scan chunk size is too small")
    root = output_root.resolve()
    if not root.is_dir():
        raise SecurityScanError("Security scan output root is unavailable")
    needles = tuple(
        value if isinstance(value, bytes) else value.encode("utf-8")
        for value in sensitive_values
        if value
    )
    max_needle = max((len(value) for value in needles), default=1)
    files_scanned = content_findings = filename_findings = symlink_findings = 0

    for path in sorted(root.rglob("*"), key=lambda item: str(item)):
        if path.is_symlink():
            symlink_findings += 1
            continue
        relative_name = str(path.relative_to(root)).encode("utf-8")
        if _contains_sensitive(relative_name, needles):
            filename_findings += 1
        if not path.is_file():
            continue
        files_scanned += 1
        overlap = b""
        found = False
        with path.open("rb") as handle:
            while chunk := handle.read(chunk_size):
                combined = overlap + chunk
                if _contains_sensitive(combined, needles):
                    found = True
                    break
                overlap = combined[-(max_needle - 1) :] if max_needle > 1 else b""
        if found:
            content_findings += 1

    return LeakageScanResult(
        files_scanned=files_scanned,
        content_findings=content_findings,
        filename_findings=filename_findings,
        symlink_findings=symlink_findings,
    )


def assert_no_leaks(output_root: Path, sensitive_values: Sequence[str | bytes]) -> None:
    result = scan_for_leaks(output_root, sensitive_values)
    if result.total_findings:
        raise SecurityScanError(
            f"Security scan found {result.total_findings} potential leak(s)"
        )
