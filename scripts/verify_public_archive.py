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

MARKDOWN_LINK_START = re.compile(r"!?\[[^\]]*\]\(")
REFERENCE_LINK = re.compile(r"^\s*\[[^\]]+\]:\s*(?:<([^>]+)>|(\S+))", re.MULTILINE)
PLACEHOLDER = re.compile(r"\b(?:TODO|TBD|REPLACE_ME)\b")


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


def inline_link_targets(content: str) -> list[str]:
    """Extract destinations with balanced or escaped parentheses."""
    targets = []
    for match in MARKDOWN_LINK_START.finditer(content):
        index = match.end()
        if index < len(content) and content[index] == "<":
            closing = content.find(">", index + 1)
            if closing != -1:
                targets.append(content[index + 1:closing])
            continue
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
        if destination and depth == 0:
            targets.append("".join(destination))
    return targets


def relative_link_errors(root: Path, markdown_files: list[Path]) -> list[str]:
    errors = []
    for source in markdown_files:
        content = source.read_text(encoding="utf-8")
        reference_targets = [match.group(1) or match.group(2) for match in REFERENCE_LINK.finditer(content)]
        for target in (*inline_link_targets(content), *reference_targets):
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith("/"):
                continue
            destination = (source.parent / unquote(parsed.path)).resolve()
            if not destination.is_relative_to(root.resolve()) or not destination.exists():
                errors.append(f"broken relative Markdown link: {source.relative_to(root)} -> {target}")
    return errors


def placeholder_errors(root: Path, markdown_files: list[Path]) -> list[str]:
    errors = []
    for source in markdown_files:
        for match in PLACEHOLDER.finditer(source.read_text(encoding="utf-8")):
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
        except (UnicodeError, OSError):
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
        *placeholder_errors(root, markdown_files),
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
