from __future__ import annotations

import importlib.util
from pathlib import Path

import defusedxml.ElementTree as ET
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate-appcast.py"
SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"


def _load_generate_appcast():
    spec = importlib.util.spec_from_file_location("generate_appcast", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generate_appcast_rejects_macos_url_without_positive_size(tmp_path):
    module = _load_generate_appcast()

    with pytest.raises(SystemExit) as excinfo:
        module.main(
            [
                "--version",
                "1.0.0",
                "--installer-url",
                "https://example.test/SeaLyonMediaManager-1.0.0-Setup.exe",
                "--installer-size",
                "12345",
                "--macos-installer-url",
                "https://example.test/SeaLyonMediaManager-1.0.0-arm64.dmg",
                "--release-url",
                "https://example.test/releases/tag/v1.0.0",
                "--output",
                str(tmp_path / "appcast.xml"),
                "--no-existing",
            ]
        )

    assert excinfo.value.code == 2


def test_generate_appcast_writes_tagged_multi_os_enclosures(tmp_path):
    module = _load_generate_appcast()
    output = tmp_path / "appcast.xml"

    assert (
        module.main(
            [
                "--version",
                "1.0.0",
                "--installer-url",
                "https://example.test/SeaLyonMediaManager-1.0.0-Setup.exe",
                "--installer-size",
                "12345",
                "--macos-installer-url",
                "https://example.test/SeaLyonMediaManager-1.0.0-arm64.dmg",
                "--macos-installer-size",
                "67890",
                "--release-url",
                "https://example.test/releases/tag/v1.0.0",
                "--output",
                str(output),
                "--no-existing",
                "--pubdate",
                "2026-06-04T12:00:00+00:00",
            ]
        )
        == 0
    )

    root = ET.fromstring(output.read_text(encoding="utf-8"))
    item = root.find("channel/item")
    assert item is not None
    enclosures = item.findall("enclosure")
    assert len(enclosures) == 2

    by_os = {
        enc.attrib[f"{{{SPARKLE_NS}}}os"]: enc
        for enc in enclosures
    }
    assert by_os["windows"].attrib["url"].endswith("-Setup.exe")
    assert by_os["windows"].attrib[f"{{{SPARKLE_NS}}}minimumSystemVersion"] == "10.0"
    assert by_os["macos"].attrib["url"].endswith("-arm64.dmg")
    assert by_os["macos"].attrib[f"{{{SPARKLE_NS}}}minimumSystemVersion"] == "11.0"


def test_generate_appcast_accepts_custom_macos_minimum_system_version(tmp_path):
    module = _load_generate_appcast()
    output = tmp_path / "appcast.xml"

    assert (
        module.main(
            [
                "--version",
                "1.0.0",
                "--installer-url",
                "https://example.test/SeaLyonMediaManager-1.0.0-Setup.exe",
                "--installer-size",
                "12345",
                "--macos-installer-url",
                "https://example.test/SeaLyonMediaManager-1.0.0-arm64.dmg",
                "--macos-installer-size",
                "67890",
                "--macos-minimum-system-version",
                "14.0",
                "--release-url",
                "https://example.test/releases/tag/v1.0.0",
                "--output",
                str(output),
                "--no-existing",
            ]
        )
        == 0
    )

    root = ET.fromstring(output.read_text(encoding="utf-8"))
    macos_enclosure = next(
        enc
        for enc in root.findall("channel/item/enclosure")
        if enc.attrib[f"{{{SPARKLE_NS}}}os"] == "macos"
    )
    assert macos_enclosure.attrib[f"{{{SPARKLE_NS}}}minimumSystemVersion"] == "14.0"


def test_generate_appcast_preserves_history_without_duplicate_version(tmp_path):
    module = _load_generate_appcast()
    output = tmp_path / "appcast.xml"
    output.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle" version="2.0">
  <channel>
    <title>Sea Lyon Media Manager</title>
    <item>
      <title>Old duplicate</title>
      <sparkle:version>1.0.0</sparkle:version>
      <enclosure url="https://example.test/old.exe" sparkle:version="1.0.0" length="1" type="application/octet-stream" />
    </item>
    <item>
      <title>Version 0.9.0</title>
      <sparkle:version>0.9.0</sparkle:version>
      <enclosure url="https://example.test/0.9.exe" sparkle:version="0.9.0" length="1" type="application/octet-stream" />
    </item>
  </channel>
</rss>
""",
        encoding="utf-8",
    )

    assert (
        module.main(
            [
                "--version",
                "1.0.0",
                "--installer-url",
                "https://example.test/SeaLyonMediaManager-1.0.0-Setup.exe",
                "--installer-size",
                "12345",
                "--release-url",
                "https://example.test/releases/tag/v1.0.0",
                "--output",
                str(output),
                "--pubdate",
                "2026-06-04T12:00:00+00:00",
            ]
        )
        == 0
    )

    versions = [
        elem.text
        for elem in ET.fromstring(output.read_text(encoding="utf-8")).findall(
            f"channel/item/{{{SPARKLE_NS}}}version"
        )
    ]
    assert versions == ["1.0.0", "0.9.0"]
