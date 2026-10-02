"""Focused behavior tests for the public archive publication gate."""

from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.verify_public_archive import REQUIRED_FILES, main


class VerifyPublicArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        for relative_path in REQUIRED_FILES:
            path = self.root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Public archive\n", encoding="utf-8")

    def verify(self, *extra_args: str) -> int:
        return main(["--root", str(self.root), *extra_args])

    def test_missing_required_file_fails(self) -> None:
        (self.root / "README.md").unlink()
        self.assertEqual(self.verify(), 1)

    def test_broken_relative_markdown_link_fails(self) -> None:
        (self.root / "README.md").write_text(
            "[missing](research/no_such_file.md)\n", encoding="utf-8"
        )
        self.assertEqual(self.verify(), 1)

    def test_placeholder_token_fails(self) -> None:
        (self.root / "README.md").write_text(
            "# Public archive\n\nTODO: complete this section.\n", encoding="utf-8"
        )
        self.assertEqual(self.verify(), 1)

    def test_supplied_redaction_pattern_match_fails(self) -> None:
        (self.root / "README.md").write_text(
            "# Public archive\n\nSensitive example marker.\n", encoding="utf-8"
        )
        redaction_file = self.root / "redaction-patterns.txt"
        redaction_file.write_text("Sensitive example marker\n", encoding="utf-8")
        self.assertEqual(self.verify("--redaction-file", str(redaction_file)), 1)


if __name__ == "__main__":
    unittest.main()
