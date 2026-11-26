"""Security, path containment, quarantine, and encoding tests for src/ingestion/."""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from src.contracts import FileFormat, ParseStatus
from src.ingestion import IngestionConfig, InputRootError, UniversalIngestor


class IngestionSecurityAndEncodingTests(unittest.TestCase):
    def test_missing_input_root_raises(self) -> None:
        ingestor = UniversalIngestor()
        with self.assertRaises(InputRootError):
            ingestor.ingest_directory(Path("non_existent_dir_12345"))

    def test_empty_oversized_and_unsupported_files_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_dir = Path(tmp) / "input"
            in_dir.mkdir()

            empty_file = in_dir / "empty.txt"
            empty_file.write_bytes(b"")

            huge_file = in_dir / "huge.txt"
            huge_file.write_text("A" * 2048, encoding="utf-8")

            pdf_file = in_dir / "attachment.pdf"
            pdf_file.write_bytes(b"%PDF-1.7 raw content")

            binary_csv = in_dir / "corrupt.csv"
            binary_csv.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")

            ingestor = UniversalIngestor(IngestionConfig(max_file_bytes=1024))
            sources = ingestor.ingest_directory(in_dir)

            by_rel = {s.relative_path: s for s in sources}
            self.assertEqual(by_rel["empty.txt"].parse_status, ParseStatus.QUARANTINED)
            self.assertEqual(by_rel["empty.txt"].quarantine_reason, "empty file")

            self.assertEqual(by_rel["huge.txt"].parse_status, ParseStatus.QUARANTINED)
            self.assertEqual(by_rel["huge.txt"].quarantine_reason, "file exceeds size limit")
            expected_huge_sha = hashlib.sha256(huge_file.read_bytes()).hexdigest()
            self.assertEqual(by_rel["huge.txt"].source_sha256, expected_huge_sha)

            self.assertEqual(by_rel["attachment.pdf"].parse_status, ParseStatus.QUARANTINED)
            self.assertEqual(by_rel["attachment.pdf"].quarantine_reason, "unsupported format")

            self.assertEqual(by_rel["corrupt.csv"].parse_status, ParseStatus.QUARANTINED)
            self.assertEqual(by_rel["corrupt.csv"].quarantine_reason, "binary content detected")

    def test_encoding_normalization_bom_utf16_cp1252(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_dir = Path(tmp) / "input"
            in_dir.mkdir()

            # UTF-8 with BOM
            bom_csv = in_dir / "bom.csv"
            bom_csv.write_bytes(b"\xef\xbb\xbfname,dose\nArif,1-0-1\n")

            # UTF-16-LE with Devanagari Hindi
            utf16_txt = in_dir / "hindi_utf16.txt"
            utf16_txt.write_bytes("मोहम्मद आरिफ BP 150/90".encode("utf-16"))

            # Windows-1252 legacy file
            cp1252_txt = in_dir / "legacy.txt"
            cp1252_txt.write_bytes("Patient: José — Dolo 650".encode("cp1252"))

            ingestor = UniversalIngestor()
            sources = ingestor.ingest_directory(in_dir)
            by_rel = {s.relative_path: s for s in sources}

            self.assertEqual(by_rel["bom.csv"].parse_status, ParseStatus.PARSED)
            self.assertEqual(by_rel["bom.csv"].encoding, "utf-8-sig")
            # Header must not retain BOM \ufeff
            self.assertEqual(by_rel["bom.csv"].records[0].fields[0].header_key, "name")

            self.assertEqual(by_rel["hindi_utf16.txt"].parse_status, ParseStatus.PARSED)
            self.assertEqual(by_rel["hindi_utf16.txt"].format, FileFormat.TEXT)
            self.assertIn("मोहम्मद आरिफ", by_rel["hindi_utf16.txt"].records[0].fields[0].raw_value)

            self.assertEqual(by_rel["legacy.txt"].parse_status, ParseStatus.PARSED)
            self.assertIn("José", by_rel["legacy.txt"].records[0].fields[0].raw_value)

    def test_symlink_is_quarantined_without_reading_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside_secret = root / "outside_secret.txt"
            outside_secret.write_text("SECRET_DO_NOT_READ", encoding="utf-8")

            in_dir = root / "input"
            in_dir.mkdir()
            link_path = in_dir / "escape.txt"
            try:
                os.symlink(outside_secret, link_path)
            except (OSError, NotImplementedError):
                self.skipTest("Symlink creation requires elevated privileges on this Windows host")

            ingestor = UniversalIngestor()
            sources = ingestor.ingest_directory(in_dir)
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0].parse_status, ParseStatus.QUARANTINED)
            self.assertEqual(sources[0].quarantine_reason, "symlink not permitted")
            self.assertEqual(sources[0].records, [])

    def test_symlink_quarantine_logic_mocked(self) -> None:
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp:
            in_dir = Path(tmp) / "input"
            (in_dir / "linked_dir").mkdir(parents=True)
            (in_dir / "linked_dir" / "inside.txt").write_text("SHOULD NOT READ", encoding="utf-8")
            (in_dir / "linked_file.txt").write_text("SHOULD NOT READ", encoding="utf-8")
            (in_dir / "normal.txt").write_text("BP 120/80", encoding="utf-8")

            orig_is_symlink = Path.is_symlink

            def fake_is_symlink(self: Path) -> bool:
                if self.name in ("linked_dir", "linked_file.txt"):
                    return True
                return orig_is_symlink(self)

            with patch.object(Path, "is_symlink", fake_is_symlink):
                sources = UniversalIngestor().ingest_directory(in_dir)

            by_rel = {s.relative_path: s for s in sources}
            self.assertNotIn("linked_dir/inside.txt", by_rel)
            self.assertEqual(by_rel["linked_dir"].parse_status, ParseStatus.QUARANTINED)
            self.assertEqual(by_rel["linked_dir"].quarantine_reason, "symlink not permitted")
            self.assertEqual(by_rel["linked_file.txt"].parse_status, ParseStatus.QUARANTINED)
            self.assertEqual(by_rel["linked_file.txt"].quarantine_reason, "symlink not permitted")
            self.assertEqual(by_rel["normal.txt"].parse_status, ParseStatus.PARSED)

    def test_inputs_are_never_modified_and_traversal_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            in_dir = Path(tmp) / "input"
            (in_dir / "b_ward").mkdir(parents=True)
            (in_dir / "a_ward").mkdir(parents=True)

            f1 = in_dir / "b_ward" / "note.txt"
            f2 = in_dir / "a_ward" / "note.txt"
            f1.write_text("Ward B note", encoding="utf-8")
            f2.write_text("Ward A note", encoding="utf-8")

            sha1_before = hashlib.sha256(f1.read_bytes()).hexdigest()
            sha2_before = hashlib.sha256(f2.read_bytes()).hexdigest()

            ingestor = UniversalIngestor()
            sources = ingestor.ingest_directory(in_dir)

            self.assertEqual([s.relative_path for s in sources], ["a_ward/note.txt", "b_ward/note.txt"])
            self.assertEqual(hashlib.sha256(f1.read_bytes()).hexdigest(), sha1_before)
            self.assertEqual(hashlib.sha256(f2.read_bytes()).hexdigest(), sha2_before)


if __name__ == "__main__":
    unittest.main()
