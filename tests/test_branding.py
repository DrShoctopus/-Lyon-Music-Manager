from __future__ import annotations

from pathlib import Path

from lyon.ui import branding


def test_branding_assets_resolve_from_source_tree() -> None:
    icon_path = branding._brand_asset_path("lyon-app-icon.png")
    splash_path = branding._brand_asset_path("lyon-splash.png")

    assert icon_path == Path("docs/brand/lyon-app-icon.png").resolve()
    assert splash_path == Path("docs/brand/lyon-splash.png").resolve()


def test_branding_assets_prefer_pyinstaller_bundle(monkeypatch, tmp_path: Path) -> None:
    bundled_brand_dir = tmp_path / "docs" / "brand"
    bundled_brand_dir.mkdir(parents=True)
    bundled_icon = bundled_brand_dir / "lyon-app-icon.png"
    bundled_icon.write_bytes(b"fake-icon")

    monkeypatch.setattr(branding.sys, "_MEIPASS", str(tmp_path), raising=False)

    assert branding._brand_asset_path("lyon-app-icon.png") == bundled_icon
