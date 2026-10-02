"""Check that the public research archive is complete and safe to publish."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit


REQUIRED_FILES = (
    ".gitignore",
    "README.md",
    "PROJECT_TIMELINE.md",
    "METHOD_EVOLUTION.md",
    "research/01_smaller_high_impact_companies/README.md",
    "research/01_smaller_high_impact_companies/public_synthesis.md",
    "research/01_smaller_high_impact_companies/sources.md",
    "research/02_employer_brand_case_studies/README.md",
    "research/02_employer_brand_case_studies/01_optiver.md",
    "research/02_employer_brand_case_studies/02_two_sigma.md",
    "research/02_employer_brand_case_studies/03_citadel_securities.md",
    "research/02_employer_brand_case_studies/04_canva.md",
    "research/02_employer_brand_case_studies/05_gitlab.md",
    "research/02_employer_brand_case_studies/cross_case_synthesis.md",
    "research/02_employer_brand_case_studies/sources.md",
    "methods/golden_samples_to_reusable_system.md",
    "methods/manual_cases_to_research_harness.md",
    "methods/evaluation_design.md",
    "references/bibliography.md",
    "references/external_links.md",
    "scripts/verify_public_archive.py",
    "tests/test_verify_public_archive.py",
)

PLACEHOLDER_TOKENS = ("TO" + "DO", "T" + "BD", "REPLACE" + "_ME")
PLACEHOLDER = re.compile(rf"\b(?:{'|'.join(PLACEHOLDER_TOKENS)})\b")


def git_files(root: Path, include_untracked: bool) -> list[Path]:
    """List tracked files, optionally including nonignored files before staging."""
    options = ["--cached", "--others", "--exclude-standard"] if include_untracked else ["--cached"]
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", *options, "-z"],
        capture_output=True,
        check=True,
    )
    return [root / path.decode("utf-8") for path in result.stdout.split(b"\0") if path]


def required_path_errors(root: Path) -> list[str]:
    return [f"missing required file: {name}" for name in REQUIRED_FILES if not (root / name).is_file()]


def link_label_end(content: str, label_start: int) -> int | None:
    """Return the index after a balanced, escape-aware Markdown label."""
    index = label_start + 1
    label_depth = 1
    while index < len(content) and label_depth:
        char = content[index]
        if char == "\\" and index + 1 < len(content):
            index += 2
            continue
        if char == "[":
            label_depth += 1
        elif char == "]":
            label_depth -= 1
        index += 1
    return index if label_depth == 0 else None


def mask_ignored_markdown(content: str) -> str:
    """Mask basic Markdown code and comment contexts before link extraction."""
    masked = list(content)

    def preceded_by_odd_backslashes(index: int) -> bool:
        backslash_count = 0
        index -= 1
        while index >= 0 and content[index] == "\\":
            backslash_count += 1
            index -= 1
        return backslash_count % 2 == 1

    def mask(start: int, end: int) -> None:
        for index in range(start, end):
            if masked[index] not in "\r\n":
                masked[index] = " "

    index = 0
    while index < len(masked):
        at_line_start = index == 0 or content[index - 1] in "\r\n"
        line_end = content.find("\n", index) + 1
        if line_end == 0:
            line_end = len(content)

        if at_line_start:
            line = content[index:line_end].rstrip("\r\n")
            fence_match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
            if fence_match:
                marker = fence_match.group(1)
                fence_end = line_end
                while fence_end < len(content):
                    closing_end = content.find("\n", fence_end) + 1
                    if closing_end == 0:
                        closing_end = len(content)
                    closing_line = content[fence_end:closing_end].rstrip("\r\n")
                    fence_end = closing_end
                    if re.match(
                        rf"^ {{0,3}}{re.escape(marker[0])}{{{len(marker)},}}[ \t]*$",
                        closing_line,
                    ):
                        break
                mask(index, fence_end)
                index = fence_end
                continue
            if content.startswith(("    ", "\t"), index):
                mask(index, line_end)
                index = line_end
                continue

        if content.startswith("<!--", index):
            comment_end = content.find("-->", index + 4)
            comment_end = len(masked) if comment_end == -1 else comment_end + 3
            mask(index, comment_end)
            index = comment_end
            continue
        if masked[index] != "`":
            index += 1
            continue
        opening_start = index
        while index < len(masked) and masked[index] == "`":
            index += 1
        marker_length = index - opening_start
        if preceded_by_odd_backslashes(opening_start):
            continue
        closing_start = index
        while closing_start < len(masked):
            if masked[closing_start] != "`":
                closing_start += 1
                continue
            closing_end = closing_start
            while closing_end < len(masked) and masked[closing_end] == "`":
                closing_end += 1
            if (
                not preceded_by_odd_backslashes(closing_start)
                and closing_end - closing_start == marker_length
            ):
                mask(opening_start, closing_end)
                index = closing_end
                break
            closing_start = closing_end
        else:
            index = opening_start + marker_length

    return "".join(masked)


def markdown_destination(content: str, start: int) -> tuple[str | None, int]:
    """Parse one escape-aware Markdown destination starting at ``start``."""
    if start >= len(content):
        return None, start
    if content[start] == "<":
        closing = content.find(">", start + 1)
        if closing == -1:
            return None, start + 1
        return content[start + 1:closing], closing + 1

    index = start
    depth = 0
    destination = []
    while index < len(content):
        char = content[index]
        if char == "\\" and index + 1 < len(content):
            index += 1
            destination.append(content[index])
        elif char == "(":
            depth += 1
            destination.append(char)
        elif char == ")":
            if depth == 0:
                break
            depth -= 1
            destination.append(char)
        elif char.isspace() and depth == 0:
            break
        else:
            destination.append(char)
        index += 1
    if not destination or depth != 0:
        return None, index
    return "".join(destination), index


def inline_link_targets(content: str) -> list[str]:
    """Extract destinations with balanced labels and parentheses."""
    targets = []
    content_index = 0
    while content_index < len(content):
        if content[content_index] == "\\":
            content_index += 2
            continue
        label_start = content_index
        if content[content_index] == "!":
            label_start += 1
        if label_start >= len(content) or content[label_start] != "[":
            content_index += 1
            continue

        index = link_label_end(content, label_start)
        if index is None or index >= len(content) or content[index] != "(":
            content_index = label_start + 1
            continue

        target, index = markdown_destination(content, index + 1)
        if target is not None:
            targets.append(target)
        content_index = index + 1
    return targets


def reference_link_targets(content: str) -> list[str]:
    """Extract reference destinations with balanced, escape-aware labels."""
    targets = []
    lines = content.splitlines()
    for line_number, line in enumerate(lines):
        label_start = 0
        while label_start < len(line) and line[label_start].isspace():
            label_start += 1
        if label_start >= len(line) or line[label_start] != "[":
            continue
        index = link_label_end(line, label_start)
        if index is None or index >= len(line) or line[index] != ":":
            continue
        index += 1
        while index < len(line) and line[index].isspace():
            index += 1
        if index >= len(line):
            if line_number + 1 >= len(lines):
                continue
            continuation = lines[line_number + 1]
            indentation = len(continuation) - len(continuation.lstrip(" "))
            if indentation not in (1, 2, 3):
                continue
            line = continuation
            index = indentation
            if index >= len(line):
                continue
        target, _ = markdown_destination(line, index)
        if target is not None:
            targets.append(target)
    return targets


def relative_link_errors(root: Path, markdown_files: list[Path]) -> list[str]:
    errors = []
    for source in markdown_files:
        try:
            content = source.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            errors.append(
                f"cannot read Markdown file: {source.relative_to(root)}: {error}"
            )
            continue
        link_content = mask_ignored_markdown(content)
        reference_targets = reference_link_targets(link_content)
        for target in (*inline_link_targets(link_content), *reference_targets):
            try:
                parsed = urlsplit(target)
            except ValueError as error:
                errors.append(
                    f"invalid Markdown link: {source.relative_to(root)} -> {target}: {error}"
                )
                continue
            if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith("/"):
                continue
            destination = (source.parent / unquote(parsed.path)).resolve()
            if not destination.is_relative_to(root.resolve()) or not destination.exists():
                errors.append(f"broken relative Markdown link: {source.relative_to(root)} -> {target}")
    return errors


def placeholder_errors(root: Path, files: list[Path]) -> list[str]:
    errors = []
    for source in files:
        if not source.is_file():
            continue
        try:
            content = source.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        except OSError as error:
            errors.append(
                f"cannot read archive text file: {source.relative_to(root)}: {error}"
            )
            continue
        for match in PLACEHOLDER.finditer(content):
            errors.append(f"placeholder token: {source.relative_to(root)}: {match.group()}")
    return errors


def redaction_errors(root: Path, files: list[Path], pattern_file: Path | None) -> list[str]:
    if pattern_file is None:
        return []
    try:
        patterns = [
            re.compile(line.strip())
            for line in pattern_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
    except (OSError, UnicodeError, re.error) as error:
        return [f"invalid redaction file: {error}"]
    errors = []
    for source in files:
        if source.resolve() == pattern_file.resolve() or not source.is_file():
            continue
        try:
            content = source.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        except OSError as error:
            errors.append(f"cannot read tracked file: {source.relative_to(root)}: {error}")
            continue
        for pattern in patterns:
            if pattern.search(content):
                errors.append(f"redaction pattern match: {source.relative_to(root)}: {pattern.pattern}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--redaction-file", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"archive root is not a directory: {root}")
    try:
        files = git_files(root, include_untracked=True)
        tracked_files = git_files(root, include_untracked=False)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"cannot list archive files: {error}")
        return 1
    markdown_files = [path for path in files if path.suffix.lower() == ".md" and path.is_file()]
    errors = [
        *required_path_errors(root),
        *relative_link_errors(root, markdown_files),
        *placeholder_errors(root, files),
        *redaction_errors(root, tracked_files, args.redaction_file),
    ]
    for error in errors:
        print(error)
    if errors:
        print(f"Archive verification failed: {len(errors)} issue(s).")
        return 1
    print("Archive verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
