"""Focused behavior tests for the public archive publication gate."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

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
            "# Public archive\n\nTO" "DO: complete this section.\n", encoding="utf-8"
        )
        self.assertEqual(self.verify(), 1)

    def test_placeholder_token_in_untracked_text_file_fails(self) -> None:
        (self.root / "research-notes.txt").write_text(
            "T" "BD after source review.\n", encoding="utf-8"
        )
        self.assertEqual(self.verify(), 1)

    def test_placeholder_token_in_tracked_text_file_fails(self) -> None:
        notes = self.root / "research-notes.txt"
        notes.write_text("REPLACE" "_ME with the citation.\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", notes.name], check=True)
        self.assertEqual(self.verify(), 1)

    def test_supplied_redaction_pattern_match_fails(self) -> None:
        (self.root / "README.md").write_text(
            "# Public archive\n\nSensitive example marker.\n", encoding="utf-8"
        )
        redaction_file = self.root / "redaction-patterns.txt"
        redaction_file.write_text("Sensitive example marker\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "README.md"], check=True)
        self.assertEqual(self.verify("--redaction-file", str(redaction_file)), 1)

    def test_untracked_text_is_not_scanned_for_redaction_patterns(self) -> None:
        redaction_file = self.root / "redaction-patterns.txt"
        redaction_file.write_text("Sensitive example marker\n", encoding="utf-8")
        (self.root / "draft.txt").write_text("Sensitive example marker\n", encoding="utf-8")
        self.assertEqual(self.verify("--redaction-file", str(redaction_file)), 0)

    def test_tracked_file_read_error_fails_redaction_check(self) -> None:
        redaction_file = self.root / "redaction-patterns.txt"
        redaction_file.write_text("Sensitive example marker\n", encoding="utf-8")
        tracked_file = self.root / "tracked-notes.txt"
        tracked_file.write_text("Reviewed source notes.\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(self.root), "add", tracked_file.name], check=True
        )
        original_read_text = Path.read_text

        def read_text(source: Path, *args: object, **kwargs: object) -> str:
            if source.resolve() == tracked_file.resolve():
                raise OSError("simulated read failure")
            return original_read_text(source, *args, **kwargs)

        output = io.StringIO()
        with patch.object(Path, "read_text", new=read_text):
            with redirect_stdout(output):
                result = self.verify("--redaction-file", str(redaction_file))

        self.assertEqual(result, 1)
        self.assertIn("cannot read tracked file: tracked-notes.txt", output.getvalue())

    def test_parenthesized_relative_markdown_link_is_checked(self) -> None:
        (self.root / "README.md").write_text(
            "[report](references/report_(final).md)\n", encoding="utf-8"
        )
        self.assertEqual(self.verify(), 1)
        (self.root / "references/report_(final).md").write_text(
            "# Report\n", encoding="utf-8"
        )
        self.assertEqual(self.verify(), 0)
        (self.root / "README.md").write_text(
            "[report](references/report_\\(final\\).md)\n", encoding="utf-8"
        )
        self.assertEqual(self.verify(), 0)
        (self.root / "references/report_(final).md").unlink()
        self.assertEqual(self.verify(), 1)

    def test_complete_archive_passes(self) -> None:
        self.assertEqual(self.verify(), 0)


if __name__ == "__main__":
    unittest.main()
