"""Filesystem security controls: path containment, symlink rejection, streaming SHA-256."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .errors import InputRootError

_CHUNK_SIZE = 65536
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


@dataclass(frozen=True, slots=True)
class DiscoveredEntry:
    """Validated file discovery descriptor before parsing."""

    abs_path: Optional[Path]
    relative_posix: str
    sha256: str
    size_bytes: int
    quarantine_reason: Optional[str] = None


def validate_input_root(input_dir: Path) -> Path:
    """Validate that input_dir is an existing, non-symlink directory."""
    if not input_dir.exists():
        raise InputRootError("Input directory does not exist.")
    if input_dir.is_symlink():
        raise InputRootError("Input root directory must not be a symlink.")
    if not input_dir.is_dir():
        raise InputRootError("Input path is not a directory.")
    return input_dir.resolve()


def compute_sha256_streaming(path: Path) -> str:
    """Compute hex SHA-256 in constant memory using 64 KiB chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def discover_input_entries(
    input_root: Path,
    max_file_bytes: int = 52_428_800,
    empty_file_action: str = "quarantine",
) -> list[DiscoveredEntry]:
    """Deterministically walk input_root without following symlinks or escaping root."""
    resolved_root = validate_input_root(input_root)
    discovered: list[DiscoveredEntry] = []

    for dirpath, dirnames, filenames in os.walk(resolved_root, topdown=True, followlinks=False):
        current_dir = Path(dirpath)

        # Prune symlinked subdirectories before os.walk descends into them.
        safe_dirnames: list[str] = []
        for dname in sorted(dirnames):
            subdir = current_dir / dname
            if subdir.is_symlink():
                rel_posix = subdir.relative_to(resolved_root).as_posix()
                discovered.append(
                    DiscoveredEntry(
                        abs_path=None,
                        relative_posix=rel_posix,
                        sha256=_EMPTY_SHA256,
                        size_bytes=0,
                        quarantine_reason="symlink not permitted",
                    )
                )
            else:
                safe_dirnames.append(dname)
        dirnames[:] = safe_dirnames

        for fname in sorted(filenames):
            candidate = current_dir / fname
            rel_posix = candidate.relative_to(resolved_root).as_posix()

            # Never open or resolve symlinks; quarantine immediately.
            if candidate.is_symlink():
                discovered.append(
                    DiscoveredEntry(
                        abs_path=None,
                        relative_posix=rel_posix,
                        sha256=_EMPTY_SHA256,
                        size_bytes=0,
                        quarantine_reason="symlink not permitted",
                    )
                )
                continue

            # Enforce containment inside resolved_root.
            try:
                resolved_file = candidate.resolve(strict=True)
            except OSError:
                discovered.append(
                    DiscoveredEntry(
                        abs_path=None,
                        relative_posix=rel_posix,
                        sha256=_EMPTY_SHA256,
                        size_bytes=0,
                        quarantine_reason="unreadable file",
                    )
                )
                continue

            if not resolved_file.is_relative_to(resolved_root) or not resolved_file.is_file():
                discovered.append(
                    DiscoveredEntry(
                        abs_path=None,
                        relative_posix=rel_posix,
                        sha256=_EMPTY_SHA256,
                        size_bytes=0,
                        quarantine_reason="path containment violation",
                    )
                )
                continue

            try:
                size_bytes = resolved_file.stat().st_size
                sha256 = compute_sha256_streaming(resolved_file)
            except OSError:
                discovered.append(
                    DiscoveredEntry(
                        abs_path=None,
                        relative_posix=rel_posix,
                        sha256=_EMPTY_SHA256,
                        size_bytes=0,
                        quarantine_reason="unreadable file",
                    )
                )
                continue

            if size_bytes == 0 and empty_file_action == "quarantine":
                discovered.append(
                    DiscoveredEntry(
                        abs_path=None,
                        relative_posix=rel_posix,
                        sha256=sha256,
                        size_bytes=0,
                        quarantine_reason="empty file",
                    )
                )
                continue

            if size_bytes > max_file_bytes:
                discovered.append(
                    DiscoveredEntry(
                        abs_path=None,
                        relative_posix=rel_posix,
                        sha256=sha256,
                        size_bytes=size_bytes,
                        quarantine_reason="file exceeds size limit",
                    )
                )
                continue

            discovered.append(
                DiscoveredEntry(
                    abs_path=resolved_file,
                    relative_posix=rel_posix,
                    sha256=sha256,
                    size_bytes=size_bytes,
                    quarantine_reason=None,
                )
            )

    discovered.sort(key=lambda item: item.relative_posix)
    return discovered
