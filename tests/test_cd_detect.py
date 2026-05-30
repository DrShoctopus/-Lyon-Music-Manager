from pathlib import Path

from lyon.core import cd_detect
from lyon.core.cd_detect import (
    _DLL_DIRECTORY_HANDLES,
    _ctdb_entries_from_windows_toc,
    _ctdb_toc_from_track_data,
    _CtdbTocEntry,
    _disc_toc_from_ctdb_entries,
    _ensure_bin_dir_on_path,
    close_dll_handles,
)


def _track_data(track_number: int, control_adr: int, offset: int) -> bytes:
    return bytes([0, control_adr, track_number, 0]) + offset.to_bytes(
        4, "big", signed=True
    )


def test_ctdb_toc_from_track_data_marks_data_track():
    entries = [
        _CtdbTocEntry(track_number=1, offset=0, is_audio=True),
        _CtdbTocEntry(track_number=2, offset=15000, is_audio=True),
        _CtdbTocEntry(track_number=3, offset=30000, is_audio=False),
        _CtdbTocEntry(
            track_number=0xAA,
            offset=45000,
            is_audio=False,
            is_leadout=True,
        ),
    ]

    assert _ctdb_toc_from_track_data(entries) == "0:15000:-30000:45000"


def test_ctdb_toc_from_track_data_requires_leadout():
    entries = [_CtdbTocEntry(track_number=1, offset=0, is_audio=True)]

    assert _ctdb_toc_from_track_data(entries) == ""


def test_disc_toc_can_be_built_from_ctdb_entries():
    toc = _disc_toc_from_ctdb_entries(
        "D:\\",
        [
            _CtdbTocEntry(track_number=1, offset=0, is_audio=True),
            _CtdbTocEntry(track_number=2, offset=15000, is_audio=True),
            _CtdbTocEntry(track_number=3, offset=30000, is_audio=False),
            _CtdbTocEntry(
                track_number=0xAA,
                offset=45000,
                is_audio=False,
                is_leadout=True,
            ),
        ],
    )

    assert toc is not None
    assert toc.drive == "D:\\"
    assert toc.discid == ""
    assert toc.toc_string == ""
    assert toc.track_count == 2
    assert toc.first_track == 1
    assert toc.last_track == 2
    assert toc.track_offsets == [0, 15000]
    assert toc.sectors == 45000
    assert toc.ctdb_toc_string == "0:15000:-30000:45000"


def test_windows_toc_parser_detects_audio_data_and_leadout_entries():
    track_data = b"".join(
        [
            _track_data(1, 0x10, 0),
            _track_data(2, 0x14, 15000),
            _track_data(0xAA, 0x10, 30000),
        ]
    )
    raw = (len(track_data) + 2).to_bytes(2, "big") + bytes([1, 2]) + track_data

    assert _ctdb_entries_from_windows_toc(raw) == [
        _CtdbTocEntry(track_number=1, offset=0, is_audio=True),
        _CtdbTocEntry(track_number=2, offset=15000, is_audio=False),
        _CtdbTocEntry(
            track_number=0xAA,
            offset=30000,
            is_audio=True,
            is_leadout=True,
        ),
    ]


def test_bin_dir_dll_handle_is_retained_and_closed(monkeypatch, tmp_path):
    class Handle:
        closed = False

        def close(self):
            self.closed = True

    handle = Handle()
    monkeypatch.setattr(cd_detect, "_bin_dir_on_path", False)
    _DLL_DIRECTORY_HANDLES.clear()
    monkeypatch.setattr(cd_detect, "bundled_bin_dir", lambda: tmp_path)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(cd_detect.os, "add_dll_directory", lambda path: handle, raising=False)

    _ensure_bin_dir_on_path()

    assert _DLL_DIRECTORY_HANDLES == [handle]
    close_dll_handles()
    assert handle.closed
    assert _DLL_DIRECTORY_HANDLES == []


def test_load_discid_prefers_bundled_macos_dylib_without_changing_cwd(monkeypatch, tmp_path):
    macos_dir = tmp_path / "Sea Lyon Media Manager.app" / "Contents" / "MacOS"
    frameworks_dir = tmp_path / "Sea Lyon Media Manager.app" / "Contents" / "Frameworks"
    macos_dir.mkdir(parents=True)
    frameworks_dir.mkdir(parents=True)
    bundled = frameworks_dir / "libdiscid.0.dylib"
    bundled.write_bytes(b"fake dylib")
    start_dir = tmp_path / "launch"
    start_dir.mkdir()
    monkeypatch.chdir(start_dir)
    monkeypatch.setattr(cd_detect.sys, "platform", "darwin")
    monkeypatch.setattr(cd_detect.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        cd_detect.sys,
        "executable",
        str(macos_dir / "LyonMusicManager"),
        raising=False,
    )
    monkeypatch.setattr(cd_detect.importlib.util, "find_spec", lambda name: object())

    monkeypatch.setattr(cd_detect.ctypes.util, "find_library", lambda name: None)

    seen_cwds: list[Path] = []
    seen_library_paths: list[str | None] = []
    sentinel = object()

    def fake_import_module(name: str):
        seen_cwds.append(Path.cwd())
        seen_library_paths.append(cd_detect.ctypes.util.find_library("discid"))
        return sentinel

    monkeypatch.setattr(cd_detect.importlib, "import_module", fake_import_module)

    assert cd_detect._load_discid() is sentinel
    assert seen_cwds == [start_dir]
    assert seen_library_paths == [str(bundled)]
    assert Path.cwd() == start_dir
