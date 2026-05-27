#!/usr/bin/env python3
"""Extract one version's section from CHANGELOG.md.

Used by the GitHub Actions release workflow to populate the Release body
from the same source-of-truth file the human edits.

Usage:
    python scripts/changelog-section.py 1.0.0
    python scripts/changelog-section.py v1.0.0      # leading "v" stripped
    python scripts/changelog-section.py --latest    # first non-Unreleased section

Writes the section (heading + body, no trailing whitespace) to stdout.
Exit codes:
    0  section found
    1  section not found / file missing
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"

# Match "## [1.0.0] — YYYY-MM-DD" and similar; accept en-dash, em-dash, hyphen.
_HEADING_RE = re.compile(
    r"^##\s+\[(?P<version>[^\]]+)\](?P<rest>.*)$"
)


def _normalise(version: str) -> str:
    return version.strip().lstrip("vV")


def _read_sections(text: str) -> list[tuple[str, str, str]]:
    """Return ``[(version, heading_line, body), ...]`` in document order.

    ``heading_line`` is the full ``## [...] — date`` line (without the
    trailing newline); ``body`` is everything up to the next ``## ``.
    """
    sections: list[tuple[str, str, str]] = []
    current_version: str | None = None
    current_heading: str | None = None
    current_body: list[str] = []
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            if current_version is not None and current_heading is not None:
                sections.append(
                    (current_version, current_heading, "\n".join(current_body).rstrip() + "\n")
                )
            current_version = _normalise(match.group("version"))
            current_heading = line
            current_body = []
        else:
            current_body.append(line)
    if current_version is not None and current_heading is not None:
        sections.append(
            (current_version, current_heading, "\n".join(current_body).rstrip() + "\n")
        )
    return sections


def extract_section(text: str, version: str) -> str | None:
    """Return the requested section (heading + body), or ``None`` if absent."""
    target = _normalise(version)
    for v, heading, body in _read_sections(text):
        if v == target:
            return f"{heading}\n{body}"
    return None


def latest_release_section(text: str) -> str | None:
    """Return the first non-Unreleased section."""
    for v, heading, body in _read_sections(text):
        if v.lower() == "unreleased":
            continue
        return f"{heading}\n{body}"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "version",
        nargs="?",
        help='Version string, e.g. "1.0.0" or "v1.0.0".',
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Print the first non-Unreleased section.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_CHANGELOG,
        help=f"Path to CHANGELOG.md (default: {DEFAULT_CHANGELOG}).",
    )
    args = parser.parse_args(argv)

    if not args.latest and not args.version:
        parser.error("either a version argument or --latest is required.")
    try:
        text = args.file.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: could not read {args.file}: {exc}", file=sys.stderr)
        return 1

    section = (
        latest_release_section(text) if args.latest else extract_section(text, args.version)
    )
    if section is None:
        target = "latest" if args.latest else args.version
        print(f"error: no section found for {target}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(section)
    if not section.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
