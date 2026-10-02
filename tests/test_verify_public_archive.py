"""Focused behavior tests for the public archive publication gate."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.verify_public_archive import (
    REQUIRED_FILES,
    inline_link_targets,
    main,
    mask_ignored_markdown,
)


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
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["--root", str(self.root), *extra_args])
        self.verifier_output = output.getvalue()
        return result

    def test_missing_required_file_fails(self) -> None:
        (self.root / "README.md").unlink()
        self.assertEqual(self.verify(), 1)

    def test_broken_relative_markdown_link_fails(self) -> None:
        (self.root / "README.md").write_text(
            "[missing](research/no_such_file.md)\n", encoding="utf-8"
        )
        self.assertEqual(self.verify(), 1)

    def test_escaped_bracket_label_relative_link_is_checked(self) -> None:
        (self.root / "README.md").write_text(
            "[review \\]](missing.md)\n", encoding="utf-8"
        )

        self.assertEqual(self.verify(), 1)
        self.assertIn(
            "broken relative Markdown link: README.md -> missing.md",
            self.verifier_output,
        )

    def test_nested_bracket_label_relative_link_is_checked(self) -> None:
        (self.root / "README.md").write_text(
            "[outer [inner]](missing.md)\n", encoding="utf-8"
        )

        self.assertEqual(self.verify(), 1)
        self.assertIn(
            "broken relative Markdown link: README.md -> missing.md",
            self.verifier_output,
        )

    def test_escaped_bracket_reference_label_relative_link_is_checked(self) -> None:
        (self.root / "README.md").write_text(
            "[review \\]]: missing.md\n", encoding="utf-8"
        )

        self.assertEqual(self.verify(), 1)
        self.assertIn(
            "broken relative Markdown link: README.md -> missing.md",
            self.verifier_output,
        )

    def test_nested_bracket_reference_label_relative_link_is_checked(self) -> None:
        (self.root / "README.md").write_text(
            "[outer [inner]]: missing.md\n", encoding="utf-8"
        )

        self.assertEqual(self.verify(), 1)
        self.assertIn(
            "broken relative Markdown link: README.md -> missing.md",
            self.verifier_output,
        )

    def test_blockquote_reference_definition_relative_link_is_checked(self) -> None:
        (self.root / "README.md").write_text(
            "> [reference]: missing.md\n", encoding="utf-8"
        )

        self.assertEqual(self.verify(), 1)
        self.assertIn(
            "broken relative Markdown link: README.md -> missing.md",
            self.verifier_output,
        )

    def test_list_item_reference_definition_relative_link_is_checked(self) -> None:
        (self.root / "README.md").write_text(
            "- [reference]: missing-list.md\n", encoding="utf-8"
        )

        self.assertEqual(self.verify(), 1)
        self.assertIn(
            "broken relative Markdown link: README.md -> missing-list.md",
            self.verifier_output,
        )

    def test_multiline_reference_definition_relative_link_is_checked(self) -> None:
        (self.root / "README.md").write_text(
            "[source]:\n  missing.md\n", encoding="utf-8"
        )

        self.assertEqual(self.verify(), 1)
        self.assertIn(
            "broken relative Markdown link: README.md -> missing.md",
            self.verifier_output,
        )

    def test_list_reference_definition_with_container_indented_destination_is_checked(self) -> None:
        (self.root / "README.md").write_text(
            "- [reference]:\n    refs/missing.md\n", encoding="utf-8"
        )

        self.assertEqual(self.verify(), 1)
        self.assertIn(
            "broken relative Markdown link: README.md -> refs/missing.md",
            self.verifier_output,
        )

    def test_blockquote_reference_definition_does_not_take_prose_as_destination(self) -> None:
        (self.root / "README.md").write_text(
            "> [reference]:\n  ordinary prose\n", encoding="utf-8"
        )

        self.assertEqual(self.verify(), 0)

    def test_multiline_reference_label_relative_link_is_checked(self) -> None:
        (self.root / "README.md").write_text(
            "[\nfoo\n]: missing.md\n", encoding="utf-8"
        )

        self.assertEqual(self.verify(), 1)
        self.assertIn(
            "broken relative Markdown link: README.md -> missing.md",
            self.verifier_output,
        )

    def test_link_shaped_text_in_fenced_code_blocks_is_ignored(self) -> None:
        (self.root / "README.md").write_text(
            "```markdown\n[inline](missing-inline.md)\n"
            "[reference]: missing-reference.md\n```\n"
            "~~~\n[tilde](missing-tilde.md)\n~~~\n",
            encoding="utf-8",
        )

        self.assertEqual(self.verify(), 0)

    def test_backtick_in_fence_info_string_does_not_open_fence(self) -> None:
        (self.root / "README.md").write_text(
            "```info`\n[missing](missing.md)\n", encoding="utf-8"
        )

        self.assertEqual(self.verify(), 1)
        self.assertIn(
            "broken relative Markdown link: README.md -> missing.md",
            self.verifier_output,
        )

    def test_link_shaped_text_in_indented_code_blocks_is_ignored(self) -> None:
        (self.root / "README.md").write_text(
            "    [inline](missing-inline.md)\n"
            "    [reference]: missing-reference.md\n"
            "\t[tab-indented](missing-tab.md)\n",
            encoding="utf-8",
        )

        self.assertEqual(self.verify(), 0)

    def test_link_shaped_text_in_list_indented_code_block_is_ignored(self) -> None:
        (self.root / "README.md").write_text(
            "- list item\n      [inline](missing-inline.md)\n",
            encoding="utf-8",
        )

        self.assertEqual(self.verify(), 0)

    def test_cr_only_line_endings_end_indented_code_mask_at_line_boundary(self) -> None:
        for line_ending in ("\n", "\r\n", "\r"):
            with self.subTest(line_ending=repr(line_ending)):
                content = (
                    f"    code{line_ending}[missing](missing.md){line_ending}"
                )
                active_links = inline_link_targets(mask_ignored_markdown(content))

                self.assertEqual(active_links, ["missing.md"])

    def test_link_shaped_text_in_inline_code_spans_is_ignored(self) -> None:
        (self.root / "README.md").write_text(
            "Examples: `[inline](missing-inline.md)` and "
            "``[reference]: missing-reference.md``.\n",
            encoding="utf-8",
        )

        self.assertEqual(self.verify(), 0)

    def test_escaped_backticks_do_not_mask_relative_link(self) -> None:
        (self.root / "README.md").write_text(
            "\\` [missing](missing.md) \\`\n", encoding="utf-8"
        )

        self.assertEqual(self.verify(), 1)
        self.assertIn(
            "broken relative Markdown link: README.md -> missing.md",
            self.verifier_output,
        )

    def test_escaped_backtick_does_not_close_inline_code_span(self) -> None:
        (self.root / "README.md").write_text(
            "`literal \\` [missing](missing.md) still code`\n", encoding="utf-8"
        )

        self.assertEqual(self.verify(), 1)
        self.assertIn(
            "broken relative Markdown link: README.md -> missing.md",
            self.verifier_output,
        )

    def test_link_shaped_text_in_html_comments_is_ignored(self) -> None:
        (self.root / "README.md").write_text(
            "<!-- [inline](missing-inline.md)\n"
            "[reference]: missing-reference.md -->\n",
            encoding="utf-8",
        )

        self.assertEqual(self.verify(), 0)

    def test_html_comment_opener_in_inline_code_does_not_hide_link(self) -> None:
        (self.root / "README.md").write_text(
            "`<!--` [missing](missing.md) -->\n", encoding="utf-8"
        )

        self.assertEqual(self.verify(), 1)
        self.assertIn(
            "broken relative Markdown link: README.md -> missing.md",
            self.verifier_output,
        )

    def test_malformed_bracketed_url_fails_with_diagnostic(self) -> None:
        (self.root / "README.md").write_text(
            "[invalid](https://[host)\n", encoding="utf-8"
        )

        self.assertEqual(self.verify(), 1)
        self.assertIn(
            "invalid Markdown link: README.md -> https://[host:",
            self.verifier_output,
        )

    def test_markdown_read_error_fails_with_diagnostic(self) -> None:
        markdown_file = self.root / "README.md"
        original_read_text = Path.read_text

        def read_text(source: Path, *args: object, **kwargs: object) -> str:
            if source.resolve() == markdown_file.resolve():
                raise OSError("simulated Markdown read failure")
            return original_read_text(source, *args, **kwargs)

        with patch.object(Path, "read_text", new=read_text):
            result = self.verify()

        self.assertEqual(result, 1)
        self.assertIn(
            "cannot read Markdown file: README.md: simulated Markdown read failure",
            self.verifier_output,
        )

    def test_non_utf8_markdown_fails_with_diagnostic(self) -> None:
        (self.root / "README.md").write_bytes(b"\xff\xfe")

        self.assertEqual(self.verify(), 1)
        self.assertIn(
            "cannot read Markdown file: README.md:",
            self.verifier_output,
        )

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

        with patch.object(Path, "read_text", new=read_text):
            result = self.verify("--redaction-file", str(redaction_file))

        self.assertEqual(result, 1)
        self.assertIn("cannot read tracked file: tracked-notes.txt", self.verifier_output)

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

    def test_escaped_parenthesized_reference_destination_resolves(self) -> None:
        (self.root / "references/report_(final).md").write_text(
            "# Report\n", encoding="utf-8"
        )
        (self.root / "README.md").write_text(
            "[report]: references/report_\\(final\\).md\n", encoding="utf-8"
        )

        self.assertEqual(self.verify(), 0)

    def test_complete_archive_passes(self) -> None:
        self.assertEqual(self.verify(), 0)


if __name__ == "__main__":
    unittest.main()
