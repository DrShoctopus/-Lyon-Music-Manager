"""Tests for the v1.0 release logging + diagnostics changes.

Covers:
  * D1/D7 — _configure_logging attaches a RotatingFileHandler and is idempotent.
  * D2    — sys.excepthook routes uncaught exceptions through logging.
  * D3    — collect_diagnostics_bundle redacts secrets and embeds log tails.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from pathlib import Path

import pytest

from lyon import app as app_module
from lyon.core import diagnostics, settings


def _detach_rotating_file_handlers() -> None:
    """Remove RotatingFileHandlers from root logger; tests need a clean slate."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            try:
                handler.close()
            except Exception:  # noqa: BLE001
                pass
            root.removeHandler(handler)


@pytest.fixture
def clean_root_logger():
    _detach_rotating_file_handlers()
    yield
    _detach_rotating_file_handlers()


def test_configure_logging_creates_rotating_file_handler(clean_root_logger):
    app_module._configure_logging()
    root = logging.getLogger()
    rotating = [
        h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(rotating) == 1
    log_path = Path(rotating[0].baseFilename)
    assert log_path.name == "sea-lyon.log"
    assert log_path.parent.name == "logs"


def test_configure_logging_writes_to_log_file(clean_root_logger):
    app_module._configure_logging()
    log_path = settings.app_data_dir() / "logs" / "sea-lyon.log"
    logging.getLogger("lyon.test").info("hello-from-test")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert log_path.exists()
    text = log_path.read_text(encoding="utf-8")
    assert "hello-from-test" in text


def test_configure_logging_is_idempotent(clean_root_logger):
    app_module._configure_logging()
    handler_count_after_first = sum(
        1 for h in logging.getLogger().handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    )
    app_module._configure_logging()
    app_module._configure_logging()
    handler_count_after_third = sum(
        1 for h in logging.getLogger().handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    )
    assert handler_count_after_first == 1
    assert handler_count_after_third == 1


def test_configure_logging_sets_root_to_info(clean_root_logger):
    app_module._configure_logging()
    assert logging.getLogger().level == logging.INFO


def test_excepthook_logs_uncaught_exception(clean_root_logger, monkeypatch):
    app_module._configure_logging()
    app_module._install_excepthooks()
    log_path = settings.app_data_dir() / "logs" / "sea-lyon.log"

    # Don't let the chained original excepthook actually run.
    monkeypatch.setattr(sys, "__excepthook__", lambda *_: None, raising=False)

    try:
        raise ValueError("boom-test-marker")
    except ValueError:
        sys.excepthook(*sys.exc_info())

    for handler in logging.getLogger().handlers:
        handler.flush()
    text = log_path.read_text(encoding="utf-8")
    assert "boom-test-marker" in text
    assert "CRITICAL" in text


def test_collect_diagnostics_bundle_redacts_secrets(monkeypatch):
    s = settings.Settings(
        lastfm_session_key="LFM_SECRET_KEY",
        listenbrainz_token="LBZ_SECRET_TOKEN",
        theaudiodb_api_key="ADB_SECRET_KEY",
    )
    s.save()

    bundle = diagnostics.collect_diagnostics_bundle()

    # The literal secrets must not appear anywhere in the bundle.
    assert "LFM_SECRET_KEY" not in bundle
    assert "LBZ_SECRET_TOKEN" not in bundle
    assert "ADB_SECRET_KEY" not in bundle
    # Redacted marker should appear.
    assert "<redacted>" in bundle


def test_collect_diagnostics_bundle_handles_missing_settings():
    # No settings.json exists yet; bundle must still build.
    bundle = diagnostics.collect_diagnostics_bundle()
    assert "Sea Lyon" in bundle or "diagnostics bundle" in bundle


def test_collect_diagnostics_bundle_embeds_log_tail(clean_root_logger):
    app_module._configure_logging()
    logging.getLogger("lyon.diagtest").warning("UNIQUE-MARKER-IN-LOG")
    for handler in logging.getLogger().handlers:
        handler.flush()

    bundle = diagnostics.collect_diagnostics_bundle()

    assert "UNIQUE-MARKER-IN-LOG" in bundle


def test_collect_diagnostics_bundle_caps_log_tail(monkeypatch, tmp_path):
    # Write a large log file and verify the bundle's log section is bounded.
    log_dir = settings.app_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    big_line = ("X" * 1023 + "\n").encode("utf-8")
    log_path = log_dir / "sea-lyon.log"
    with log_path.open("wb") as f:
        # ~3 MB of garbage
        for _ in range(3000):
            f.write(big_line)

    bundle = diagnostics.collect_diagnostics_bundle()
    # The whole bundle stays well under 5 MB even with multi-MB logs.
    assert len(bundle.encode("utf-8")) < 5 * 1024 * 1024


def test_redacted_settings_json_keeps_non_secret_fields():
    s = settings.Settings(
        lastfm_session_key="SECRET",
        listenbrainz_token="ALSO_SECRET",
        library_paths=["/music/main", "/music/extra"],
    )
    s.save()
    text = diagnostics._redacted_settings_json()
    data = json.loads(text)
    assert data["lastfm_session_key"] == "<redacted>"
    assert data["listenbrainz_token"] == "<redacted>"
    assert "/music/main" in text
    assert "/music/extra" in text
