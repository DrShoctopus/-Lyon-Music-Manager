#!/usr/bin/env python3
"""Generate / refresh the Sea Lyon appcast.xml file.

The in-app updater (``lyon.core.updater``) polls a Sparkle-style XML feed
to detect new releases. We host that feed on GitHub Pages (the
``gh-pages`` branch or a published ``/docs`` folder). This script is run
by the release workflow after a tag push to either:

  1. Create a brand-new ``appcast.xml`` (when nothing exists yet), or
  2. Prepend a new ``<item>`` for the freshly-tagged release and trim
     older entries so the file stays bounded.

The release-notes HTML is read from CHANGELOG.md via the companion
``scripts/changelog-section.py``.

Usage:
    python scripts/generate-appcast.py \\
        --version 1.0.0 \\
        --installer-url https://github.com/.../SeaLyonMediaManager-1.0.0-Setup.exe \\
        --installer-size 12345678 \\
        --release-url https://github.com/.../releases/tag/v1.0.0 \\
        --output appcast.xml

Existing items are preserved (up to ``--max-items``, default 10).
"""
from __future__ import annotations

import argparse
import html
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import defusedxml.ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHANGELOG = REPO_ROOT / "CHANGELOG.md"
DEFAULT_APPCAST = REPO_ROOT / "appcast.xml"
DEFAULT_TITLE = "Sea Lyon Media Manager"
DEFAULT_DESCRIPTION = "Release feed for Sea Lyon Media Manager."
DEFAULT_LINK = "https://github.com/DrShoctopus/Sea-Lyon-Media-Manager"

SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"


def _rss_date(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


def _release_notes_html(version: str, changelog_path: Path) -> str:
    """Run scripts/changelog-section.py for the version and return HTML.

    The CHANGELOG is markdown; we keep the conversion deliberately
    minimal (escape HTML, preserve bullet structure) so we don't pull
    in a markdown dependency for a tiny script. Sparkle viewers and
    QTextBrowser both render the result fine.
    """
    script = Path(__file__).with_name("changelog-section.py")
    try:
        result = subprocess.run(
            [sys.executable, str(script), version, "--file", str(changelog_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr)
        raise SystemExit(
            f"changelog-section.py could not find version {version!r}."
        ) from exc
    md = result.stdout
    return _markdown_to_simple_html(md)


def _markdown_to_simple_html(md: str) -> str:
    """Convert the changelog snippet into safe-ish HTML.

    Handles ``##`` and ``###`` headings plus ``-``/``*`` bullet lists.
    Everything else passes through as escaped paragraphs.
    """
    lines = md.splitlines()
    out: list[str] = []
    in_ul = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{html.escape(stripped[2:])}</li>")
            continue
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if not stripped:
            out.append("")
            continue
        if stripped.startswith("### "):
            out.append(f"<h4>{html.escape(stripped[4:])}</h4>")
        elif stripped.startswith("## "):
            out.append(f"<h3>{html.escape(stripped[3:])}</h3>")
        else:
            out.append(f"<p>{html.escape(stripped)}</p>")
    if in_ul:
        out.append("</ul>")
    return "\n".join(out).strip()


def _load_existing_items(path: Path) -> list[ET.Element]:
    if not path.exists():
        return []
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8"))
    except Exception as exc:
        sys.stderr.write(f"warning: could not parse existing appcast at {path}: {exc}\n")
        return []
    channel = root.find("channel")
    if channel is None:
        return []
    return list(channel.findall("item"))


def _item_version(item: ET.Element) -> str:
    elem = item.find(f"{{{SPARKLE_NS}}}version")
    if elem is None or not elem.text:
        return ""
    return elem.text.strip()


def _build_appcast_xml(
    *,
    title: str,
    description: str,
    link: str,
    items_xml: list[str],
) -> str:
    items_block = "\n".join(items_xml)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle"\n'
        '     xmlns:dc="http://purl.org/dc/elements/1.1/"\n'
        '     version="2.0">\n'
        '  <channel>\n'
        f'    <title>{html.escape(title)}</title>\n'
        f'    <link>{html.escape(link)}</link>\n'
        f'    <description>{html.escape(description)}</description>\n'
        '    <language>en</language>\n'
        f'{items_block}\n'
        '  </channel>\n'
        '</rss>\n'
    )


def _enclosure_xml(
    url: str,
    version: str,
    size: int,
    *,
    os_tag: str | None = None,
    minimum_system_version: str = "",
) -> str:
    attrs = (
        f'url="{html.escape(url, quote=True)}" '
        f'sparkle:version="{html.escape(version)}" '
        f'length="{int(size)}" '
        'type="application/octet-stream"'
    )
    if os_tag:
        attrs += f' sparkle:os="{html.escape(os_tag)}"'
    if minimum_system_version:
        attrs += f' sparkle:minimumSystemVersion="{html.escape(minimum_system_version)}"'
    return f'      <enclosure {attrs} />'


def _serialise_item(
    *,
    version: str,
    pub_date: datetime,
    title: str,
    release_url: str,
    installer_url: str,
    installer_size: int,
    minimum_system_version: str,
    release_notes_html: str,
    macos_installer_url: str = "",
    macos_installer_size: int = 0,
    macos_minimum_system_version: str = "11.0",
) -> str:
    enclosures: list[str] = []
    if macos_installer_url:
        # Emit tagged enclosures so the client can pick the right one per OS
        enclosures.append(_enclosure_xml(
            installer_url,
            version,
            installer_size,
            os_tag="windows",
            minimum_system_version=minimum_system_version,
        ))
        enclosures.append(_enclosure_xml(
            macos_installer_url, version, macos_installer_size,
            os_tag="macos", minimum_system_version=macos_minimum_system_version,
        ))
    else:
        # Legacy single-enclosure (Windows-only release)
        enclosures.append(_enclosure_xml(
            installer_url, version, installer_size,
            minimum_system_version=minimum_system_version,
        ))
    enc_block = "\n".join(enclosures)
    return (
        '    <item>\n'
        f'      <title>{html.escape(title)}</title>\n'
        f'      <pubDate>{_rss_date(pub_date)}</pubDate>\n'
        f'      <sparkle:version>{html.escape(version)}</sparkle:version>\n'
        f'      <link>{html.escape(release_url)}</link>\n'
        '      <description><![CDATA[\n'
        f'{release_notes_html}\n'
        '      ]]></description>\n'
        f'{enc_block}\n'
        '    </item>'
    )


def _existing_item_xml(item: ET.Element) -> str:
    return ET.tostring(item, encoding="unicode").rstrip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Release version, e.g. 1.0.0.")
    parser.add_argument(
        "--installer-url",
        required=True,
        help="Public URL of the Windows .exe installer for this release.",
    )
    parser.add_argument(
        "--installer-size",
        type=int,
        required=True,
        help="Size in bytes of the Windows installer (for Sparkle enclosure length).",
    )
    parser.add_argument(
        "--macos-installer-url",
        default="",
        help="Public URL of the macOS arm64 .dmg for this release (omit for Windows-only).",
    )
    parser.add_argument(
        "--macos-installer-size",
        type=int,
        default=0,
        help="Size in bytes of the macOS .dmg.",
    )
    parser.add_argument(
        "--macos-minimum-system-version",
        default="11.0",
        help="Minimum macOS version for the DMG enclosure (default: 11.0).",
    )
    parser.add_argument(
        "--release-url",
        required=True,
        help="Public URL of the GitHub Release page for this version.",
    )
    parser.add_argument(
        "--changelog",
        type=Path,
        default=DEFAULT_CHANGELOG,
        help=f"Path to CHANGELOG.md (default: {DEFAULT_CHANGELOG}).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_APPCAST,
        help=f"Where to write appcast.xml (default: {DEFAULT_APPCAST}).",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=10,
        help="How many historical <item> entries to retain (default: 10).",
    )
    parser.add_argument(
        "--minimum-system-version",
        default="10.0",
        help="Minimum Windows version for the release (default: 10.0).",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Per-release <title>. Defaults to 'Version {version}'.",
    )
    parser.add_argument(
        "--pubdate",
        default=None,
        help="ISO 8601 timestamp for the release (default: now, UTC).",
    )
    parser.add_argument(
        "--no-existing",
        action="store_true",
        help="Ignore any existing appcast.xml and start fresh (useful for the first release).",
    )
    args = parser.parse_args(argv)

    if args.installer_size <= 0:
        parser.error("--installer-size must be greater than 0.")
    if args.macos_installer_url and args.macos_installer_size <= 0:
        parser.error("--macos-installer-size must be greater than 0 when --macos-installer-url is set.")
    if args.macos_installer_size > 0 and not args.macos_installer_url:
        parser.error("--macos-installer-url is required when --macos-installer-size is set.")

    pub_date = (
        datetime.fromisoformat(args.pubdate)
        if args.pubdate
        else datetime.now(timezone.utc)
    )
    release_notes = _release_notes_html(args.version, args.changelog)
    new_item = _serialise_item(
        version=args.version,
        pub_date=pub_date,
        title=args.title or f"Version {args.version}",
        release_url=args.release_url,
        installer_url=args.installer_url,
        installer_size=args.installer_size,
        minimum_system_version=args.minimum_system_version,
        release_notes_html=release_notes,
        macos_installer_url=args.macos_installer_url,
        macos_installer_size=args.macos_installer_size,
        macos_minimum_system_version=args.macos_minimum_system_version,
    )

    items_xml: list[str] = [new_item]
    if not args.no_existing:
        for item in _load_existing_items(args.output):
            if _item_version(item) == args.version:
                continue  # don't duplicate the version we're inserting
            items_xml.append(_existing_item_xml(item))

    items_xml = items_xml[: args.max_items]
    xml = _build_appcast_xml(
        title=DEFAULT_TITLE,
        description=DEFAULT_DESCRIPTION,
        link=DEFAULT_LINK,
        items_xml=items_xml,
    )
    args.output.write_text(xml, encoding="utf-8")
    print(
        f"Wrote appcast with {len(items_xml)} item(s) -> {args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
