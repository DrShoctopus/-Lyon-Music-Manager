"""Tests for lyon.core.fingerprint and related library methods."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from lyon.core.fingerprint import (
    api_key,
    fingerprint_file,
    is_available,
    is_lookup_configured,
    lookup_candidates,
)

# ------------------------------------------------------------------ is_available

class TestIsAvailable:
    def test_false_when_acoustid_missing(self, monkeypatch):
        import builtins
        real_import = builtins.__import__
        def fake_import(name, *args, **kwargs):
            if name == "acoustid":
                raise ImportError("no module")
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert not is_available()

    def test_true_when_acoustid_and_fpcalc_present(self, monkeypatch, tmp_path):
        # Fake a fpcalc binary in tmp_path/bin/
        import sys
        binary = "fpcalc.exe" if sys.platform == "win32" else "fpcalc"
        (tmp_path / "bin").mkdir()
        fake_bin = tmp_path / "bin" / binary
        fake_bin.write_text("fake")
        fake_bin.chmod(0o755)

        monkeypatch.setattr("lyon.core.fingerprint._fpcalc_path", lambda: str(fake_bin))
        with patch("lyon.core.fingerprint._set_fpcalc"):
            try:
                import acoustid  # noqa: F401
                assert is_available()
            except ImportError:
                pytest.skip("pyacoustid not installed")


class TestApiKey:
    def test_empty_when_constant_and_environment_missing(self, monkeypatch):
        monkeypatch.setattr("lyon.core.fingerprint.ACOUSTID_API_KEY", "")
        monkeypatch.delenv("ACOUSTID_API_KEY", raising=False)

        assert api_key() == ""
        assert not is_lookup_configured()

    def test_environment_overrides_constant(self, monkeypatch):
        monkeypatch.setattr("lyon.core.fingerprint.ACOUSTID_API_KEY", "constant-key")
        monkeypatch.setenv("ACOUSTID_API_KEY", " env-key ")

        assert api_key() == "env-key"
        assert is_lookup_configured()


# ------------------------------------------------------------------ fingerprint_file

class TestFingerprintFile:
    def test_returns_none_on_acoustid_import_error(self, monkeypatch):
        import builtins
        real_import = builtins.__import__
        def fake_import(name, *args, **kwargs):
            if name == "acoustid":
                raise ImportError
            return real_import(name, *args, **kwargs)
        monkeypatch.setattr(builtins, "__import__", fake_import)
        result = fingerprint_file("/nonexistent/path.flac")
        assert result is None

    def test_returns_none_on_exception(self, monkeypatch):
        pytest.importorskip("acoustid")
        monkeypatch.setattr("acoustid.fingerprint_file", lambda *a, **kw: (_ for _ in ()).throw(Exception("fail")))
        result = fingerprint_file("/nonexistent/path.flac")
        assert result is None

    def test_returns_tuple_on_success(self, monkeypatch):
        pytest.importorskip("acoustid")
        monkeypatch.setattr("acoustid.fingerprint_file", lambda path: (180, "AQADtM..."))
        result = fingerprint_file("/fake/file.flac")
        assert result is not None
        duration, fp = result
        assert isinstance(duration, int)
        assert isinstance(fp, str)


# ------------------------------------------------------------------ lookup_candidates

class TestLookupCandidates:
    def test_empty_when_no_api_key(self, monkeypatch):
        monkeypatch.setattr("lyon.core.fingerprint.ACOUSTID_API_KEY", "")
        monkeypatch.delenv("ACOUSTID_API_KEY", raising=False)
        result = lookup_candidates("/some/file.flac")
        assert result == []

    def test_empty_when_fingerprint_fails(self, monkeypatch):
        monkeypatch.setattr("lyon.core.fingerprint.ACOUSTID_API_KEY", "testkey")
        monkeypatch.delenv("ACOUSTID_API_KEY", raising=False)
        monkeypatch.setattr("lyon.core.fingerprint.fingerprint_file", lambda p: None)
        result = lookup_candidates("/some/file.flac")
        assert result == []

    def test_returns_candidates_on_success(self, monkeypatch):
        pytest.importorskip("acoustid")

        monkeypatch.setattr("lyon.core.fingerprint.ACOUSTID_API_KEY", "testkey")
        monkeypatch.delenv("ACOUSTID_API_KEY", raising=False)
        monkeypatch.setattr("lyon.core.fingerprint.fingerprint_file", lambda p: (180, "AQAD"))

        fake_response = {
            "status": "ok",
            "results": [
                {
                    "id": "acoustid-uuid-1",
                    "score": 0.99,
                    "recordings": [
                        {
                            "id": "mbid-1",
                            "title": "Test Song",
                            "artists": [{"name": "Test Artist"}],
                            "releases": [{"id": "rel-1", "title": "Test Album"}],
                        }
                    ],
                }
            ],
        }
        monkeypatch.setattr("acoustid.lookup", lambda *a, **kw: fake_response)
        monkeypatch.setattr(
            "acoustid.parse_lookup_result",
            lambda data: [(0.99, "mbid-1", "Test Song", "Test Artist")],
        )

        result = lookup_candidates("/some/file.flac")
        assert len(result) == 1
        assert result[0]["title"] == "Test Song"
        assert result[0]["artist"] == "Test Artist"
        assert result[0]["score"] == pytest.approx(0.99)

    def test_sorted_by_score_descending(self, monkeypatch):
        pytest.importorskip("acoustid")

        monkeypatch.setattr("lyon.core.fingerprint.ACOUSTID_API_KEY", "testkey")
        monkeypatch.delenv("ACOUSTID_API_KEY", raising=False)
        monkeypatch.setattr("lyon.core.fingerprint.fingerprint_file", lambda p: (180, "AQAD"))
        monkeypatch.setattr("acoustid.lookup", lambda *a, **kw: {"status": "ok", "results": []})
        monkeypatch.setattr(
            "acoustid.parse_lookup_result",
            lambda data: [
                (0.7, "mbid-2", "Second", "B"),
                (0.99, "mbid-1", "First", "A"),
            ],
        )

        result = lookup_candidates("/some/file.flac")
        assert result[0]["score"] > result[1]["score"]

    def test_empty_on_acoustid_exception(self, monkeypatch):
        pytest.importorskip("acoustid")

        monkeypatch.setattr("lyon.core.fingerprint.ACOUSTID_API_KEY", "testkey")
        monkeypatch.delenv("ACOUSTID_API_KEY", raising=False)
        monkeypatch.setattr("lyon.core.fingerprint.fingerprint_file", lambda p: (180, "AQAD"))
        monkeypatch.setattr("acoustid.lookup", lambda *a, **kw: (_ for _ in ()).throw(Exception("net error")))

        result = lookup_candidates("/some/file.flac")
        assert result == []


# ------------------------------------------------------------------ library integration

def _add_track(lib, path: str, bitrate: int = 320_000) -> None:
    """Insert a minimal audio row directly — avoids needing a real audio file."""
    from pathlib import Path as _Path
    lib.conn.execute(
        "INSERT INTO tracks "
        "(path, title, artist, album_artist, album, track_no, disc_no, year, genre, "
        " duration, bitrate, samplerate, media_type) "
        "VALUES (?, ?, 'Artist', 'Artist', 'Album', 1, 1, 0, '', 120.0, ?, 44100, 'audio')",
        (path, _Path(path).stem, bitrate),
    )
    lib.conn.commit()


class TestLibraryFingerprintMethods:
    def test_update_acoustid_and_find_duplicates(self, tmp_path):
        from lyon.core.library import Library
        lib = Library(str(tmp_path / "test.db"))

        _add_track(lib, str(tmp_path / "a.flac"))
        _add_track(lib, str(tmp_path / "b.flac"))
        tracks = lib.tracks_without_acoustid()
        assert len(tracks) == 2

        lib.update_acoustid(tracks[0].id, "acoustid-xyz")
        lib.update_acoustid(tracks[1].id, "acoustid-xyz")

        groups = lib.find_duplicates_by_fingerprint()
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_tracks_without_acoustid_default(self, tmp_path):
        from lyon.core.library import Library
        lib = Library(str(tmp_path / "test.db"))
        path = str(tmp_path / "track.flac")
        _add_track(lib, path)

        without = lib.tracks_without_acoustid()
        assert any(t.path == path for t in without)

    def test_tracks_without_acoustid_count_and_paged_iterator(self, tmp_path):
        from lyon.core.library import Library
        lib = Library(str(tmp_path / "test.db"))
        paths = [str(tmp_path / f"track-{i}.flac") for i in range(5)]
        for path in paths:
            _add_track(lib, path)
        tracks = lib.tracks_without_acoustid()
        lib.update_acoustid(tracks[0].id, "known-id")

        assert lib.count_tracks(media_type="audio") == 5
        assert lib.count_tracks_without_acoustid() == 4
        paged = list(lib.iter_tracks_without_acoustid(batch_size=2))
        assert len(paged) == 4
        assert tracks[0].id not in {track.id for track in paged}
        assert [track.id for track in lib.tracks_without_acoustid()] == [
            track.id for track in paged
        ]

    def test_update_acoustid_removes_from_without_list(self, tmp_path):
        from lyon.core.library import Library
        lib = Library(str(tmp_path / "test.db"))
        path = str(tmp_path / "track.flac")
        _add_track(lib, path)

        tracks = lib.tracks_without_acoustid()
        assert tracks

        lib.update_acoustid(tracks[0].id, "some-id")
        without_after = lib.tracks_without_acoustid()
        assert not any(t.id == tracks[0].id for t in without_after)

    def test_no_duplicates_by_fingerprint_when_different_ids(self, tmp_path):
        from lyon.core.library import Library
        lib = Library(str(tmp_path / "test.db"))

        _add_track(lib, str(tmp_path / "a.flac"))
        _add_track(lib, str(tmp_path / "b.flac"))
        tracks = lib.tracks_without_acoustid()

        lib.update_acoustid(tracks[0].id, "id-one")
        lib.update_acoustid(tracks[1].id, "id-two")

        groups = lib.find_duplicates_by_fingerprint()
        assert groups == []

    def test_find_duplicates_ignores_null_acoustid(self, tmp_path):
        from lyon.core.library import Library
        lib = Library(str(tmp_path / "test.db"))

        _add_track(lib, str(tmp_path / "a.flac"))
        _add_track(lib, str(tmp_path / "b.flac"))
        # Leave acoustid as NULL — should not appear as duplicates
        groups = lib.find_duplicates_by_fingerprint()
        assert groups == []

    def test_find_duplicates_by_fingerprint_best_quality_first(self, tmp_path):
        from lyon.core.library import Library
        lib = Library(str(tmp_path / "test.db"))

        _add_track(lib, str(tmp_path / "lo.flac"), bitrate=128_000)
        _add_track(lib, str(tmp_path / "hi.flac"), bitrate=320_000)
        tracks = lib.tracks_without_acoustid()
        for t in tracks:
            lib.update_acoustid(t.id, "same-id")

        groups = lib.find_duplicates_by_fingerprint()
        assert len(groups) == 1
        # Higher bitrate should be first (group[0] = best)
        assert groups[0][0].bitrate >= groups[0][1].bitrate

    def test_reindex_changed_audio_clears_stale_acoustid(self, tmp_path, monkeypatch):
        from lyon.core import library as library_module
        from lyon.core.library import Library

        class _FakeInfo:
            length = 60.0
            bitrate = 320_000
            sample_rate = 44_100

        class _FakeAudio(dict):
            info = _FakeInfo()

            def get(self, key):
                return {
                    "title": ["Song"],
                    "artist": ["Artist"],
                    "albumartist": ["Artist"],
                    "album": ["Album"],
                    "tracknumber": ["1"],
                    "discnumber": ["1"],
                    "date": ["2024"],
                    "genre": ["Rock"],
                }.get(key)

        monkeypatch.setattr(library_module, "MutagenFile", lambda *_a, **_k: _FakeAudio())

        audio = tmp_path / "song.flac"
        audio.write_bytes(b"a" * 200_000)
        os.utime(audio, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))

        lib = Library(str(tmp_path / "test.db"))
        assert lib.index_file(audio).status == "added"
        lib.commit()
        track = next(lib.all_tracks())
        lib.update_acoustid(track.id, "stale-id")

        audio.write_bytes(b"b" * 200_000)
        os.utime(audio, ns=(1_700_000_100_000_000_000, 1_700_000_100_000_000_000))
        assert lib.index_file(audio).status == "updated"
        lib.commit()

        row = lib.conn.execute(
            "SELECT acoustid_id FROM tracks WHERE id = ?", (track.id,)
        ).fetchone()
        assert row["acoustid_id"] is None
        assert any(t.id == track.id for t in lib.tracks_without_acoustid())
