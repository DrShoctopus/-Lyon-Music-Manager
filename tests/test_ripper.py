import io
import importlib.util
import sys
import types


def _install_dependency_stubs() -> bool:
    try:
        import PySide6.QtCore  # noqa: F401
        import PySide6.QtGui  # noqa: F401
        import PySide6.QtWidgets  # noqa: F401
        need_pyside_stubs = False
    except ImportError:
        need_pyside_stubs = True

    if need_pyside_stubs:
        pyside = types.ModuleType("PySide6")
        qtcore = types.ModuleType("PySide6.QtCore")

        class _Signal:
            def __init__(self, *_, **__):
                self._callbacks = []

            def connect(self, callback):
                self._callbacks.append(callback)

            def emit(self, *args):
                for callback in list(self._callbacks):
                    callback(*args)

        class _QObject:
            def __init__(self, *_, **__):
                pass

            def moveToThread(self, *_):
                pass

            def deleteLater(self):
                pass

        class _QThread:
            started = _Signal()

            def __init__(self, *_, **__):
                pass

            def isRunning(self):
                return False

            def start(self):
                pass

            def quit(self):
                pass

            def wait(self):
                pass

        qtgui = types.ModuleType("PySide6.QtGui")
        qtwidgets = types.ModuleType("PySide6.QtWidgets")

        class _Qt:
            AlignCenter = 1
            ElideRight = 1
            KeepAspectRatio = 1
            SmoothTransformation = 1
            UserRole = 1

        class _QSize:
            def __init__(self, *_, **__):
                pass

        class _Widget:
            def __init__(self, *_, **__):
                pass

        class _QMessageBox(_Widget):
            Yes = 1
            No = 0

            @staticmethod
            def information(*_, **__):
                pass

            @staticmethod
            def question(*_, **__):
                return _QMessageBox.No

        qtcore.QObject = _QObject
        qtcore.QThread = _QThread
        qtcore.Signal = _Signal
        qtcore.Qt = _Qt
        qtcore.QSize = _QSize
        qtcore.QTimer = _Widget
        qtgui.QColor = _Widget
        qtgui.QPainter = _Widget
        qtgui.QPainter.Antialiasing = 1
        qtgui.QPixmap = _Widget
        qtgui.QStandardItem = _Widget
        qtgui.QStandardItemModel = _Widget
        for name in (
            "QAbstractItemView", "QComboBox", "QHBoxLayout", "QHeaderView",
            "QLabel", "QLineEdit", "QProgressBar", "QPushButton", "QStyle",
            "QStyleOptionProgressBar", "QStyledItemDelegate", "QTableView",
            "QVBoxLayout", "QWidget",
        ):
            setattr(qtwidgets, name, _Widget)
        qtwidgets.QMessageBox = _QMessageBox
        qtwidgets.QStyle.CE_ProgressBar = 1
        sys.modules["PySide6"] = pyside
        sys.modules["PySide6.QtCore"] = qtcore
        sys.modules["PySide6.QtGui"] = qtgui
        sys.modules["PySide6.QtWidgets"] = qtwidgets

    if importlib.util.find_spec("musicbrainzngs") is None:
        musicbrainzngs = types.ModuleType("musicbrainzngs")
        musicbrainzngs.ResponseError = Exception
        musicbrainzngs.NetworkError = Exception
        sys.modules["musicbrainzngs"] = musicbrainzngs

    if importlib.util.find_spec("requests") is None:
        requests = types.ModuleType("requests")
        requests.RequestException = Exception
        sys.modules["requests"] = requests

    return need_pyside_stubs


_PYSIDE_STUBBED = _install_dependency_stubs()

from lyon.core.cd_detect import DiscToc  # noqa: E402
from lyon.core.metadata import AlbumInfo, TrackInfo  # noqa: E402
from lyon.core.settings import Settings  # noqa: E402
from lyon.core.ripper import (  # noqa: E402
    CDDA_SECTOR_SIZE,
    FfmpegAttemptFailure,
    RipFailure,
    RipRequest,
    RipWorker,
    WINDOWS_CDDA_FALLBACK_READ_CHUNK_SECTORS,
    WINDOWS_CDDA_INITIAL_READ_CHUNK_SECTORS,
    _WindowsCddaReadError,
    _WindowsCddaReader,
    _build_libcdio_track_command,
    _build_raw_cdda_ffmpeg_command,
    _ffmpeg_format_listing_has_demuxer,
    _parse_progress,
    _summarize_ffmpeg_failure,
    _track_sector_span,
    _unique_track_output,
    _windows_cdda_drive_path,
    _write_failure_log,
    format_extension,
    safe_path_component,
    target_file,
    target_folder,
    track_output_files,
    unique_target_folder,
)
from lyon.ui import ripper_view as ripper_view_module  # noqa: E402
from lyon.ui.ripper_view import RipperView, _existing_target_files, _rip_request_from_toc  # noqa: E402

if _PYSIDE_STUBBED:
    for _module_name in ("PySide6.QtWidgets", "PySide6.QtGui", "PySide6.QtCore", "PySide6"):
        sys.modules.pop(_module_name, None)


def test_track_sector_span_normalises_musicbrainz_toc_offsets():
    offsets = (150, 15150, 30150)

    assert _track_sector_span(1, offsets, 45150) == (0, 15000)
    assert _track_sector_span(2, offsets, 45150) == (15000, 30000)
    assert _track_sector_span(3, offsets, 45150) == (30000, 45000)


def test_libcdio_command_extracts_one_audio_stream_with_toc_timing(tmp_path):
    out = tmp_path / "track.flac"

    cmd = _build_libcdio_track_command(
        "ffmpeg",
        "D:",
        out,
        ["-c:a", "flac", "-compression_level", "8"],
        (15000, 30000),
        input_seek=True,
    )

    assert cmd[cmd.index("-ss") + 1] == "200"
    assert cmd[cmd.index("-t") + 1] == "200"
    assert cmd[cmd.index("-map") + 1] == "0:a:0"
    assert "0:a:1" not in cmd
    assert cmd[-1] == str(out)


def test_raw_cdda_command_uses_ffmpeg_as_flac_encoder(tmp_path):
    out = tmp_path / "track.flac"

    cmd = _build_raw_cdda_ffmpeg_command(
        "ffmpeg",
        out,
        ["-c:a", "flac", "-compression_level", "5"],
    )

    assert cmd[cmd.index("-f") + 1] == "s16le"
    assert cmd[cmd.index("-ar") + 1] == "44100"
    assert cmd[cmd.index("-ac") + 1] == "2"
    assert cmd[cmd.index("-i") + 1] == "pipe:0"
    assert cmd[cmd.index("-c:a") + 1] == "flac"
    assert cmd[cmd.index("-compression_level") + 1] == "5"
    assert "libcdio" not in cmd
    assert cmd[-1] == str(out)


def test_parse_ffmpeg_progress_uses_track_duration():
    line = "size=  1024kB time=00:01:15.00 bitrate=1118.5kbits/s"

    assert _parse_progress(line, 150) == 50


def test_parse_ffmpeg_progress_bounds_before_completion():
    line = "size=  2048kB time=00:03:00.00 bitrate=1118.5kbits/s"

    assert _parse_progress(line, 150) == 99


def test_parse_ffmpeg_progress_ignores_lines_without_time():
    assert _parse_progress("ffmpeg diagnostic", 150) is None
    assert _parse_progress("time=00:00:01.00", 0) is None


class _FakeFfmpegProcess:
    def __init__(self, stdout: bytes, returncode: int | None = None):
        self.stdout = io.BytesIO(stdout)
        self.returncode = returncode
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 1
        return self.returncode


def _rip_worker(tmp_path) -> RipWorker:
    album = AlbumInfo(artist="Artist", album="Album")
    request = RipRequest("D:", album, tmp_path)
    return RipWorker(Settings(), request)


def test_run_ffmpeg_cancel_terminates_process_and_removes_partial(monkeypatch, tmp_path):
    proc = _FakeFfmpegProcess(b"size=1kB time=00:00:01.00\r", returncode=None)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: proc)
    out = tmp_path / "partial.flac"
    out.write_bytes(b"partial")
    worker = _rip_worker(tmp_path)
    worker.cancel()

    failure = worker._run_ffmpeg(["ffmpeg"], 1, out, 10.0)

    assert failure is not None
    assert failure.reason == "Cancelled by user."
    assert proc.terminated
    assert not out.exists()


def test_run_ffmpeg_captures_carriage_return_output(monkeypatch, tmp_path):
    proc = _FakeFfmpegProcess(
        b"frame=1 time=00:00:01.00\rsize=2kB time=00:00:02.00\r",
        returncode=None,
    )
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: proc)
    out = tmp_path / "failed.flac"
    worker = _rip_worker(tmp_path)

    failure = worker._run_ffmpeg(["ffmpeg"], 1, out, 10.0)

    assert failure is not None
    assert failure.returncode == 1
    assert failure.output == [
        "frame=1 time=00:00:01.00",
        "size=2kB time=00:00:02.00",
    ]


def test_ffmpeg_format_listing_detects_libcdio_demuxer():
    listing = """
Formats:
 D.. = Demuxing supported
 .E. = Muxing supported
 D d libcdio         libcdio CDDA input
  E  flac            raw FLAC
"""

    assert _ffmpeg_format_listing_has_demuxer(listing, "libcdio")
    assert not _ffmpeg_format_listing_has_demuxer(listing, "flac")


def test_windows_cdda_drive_path_normalises_drive_letters():
    assert _windows_cdda_drive_path("D:") == "\\\\.\\D:"
    assert _windows_cdda_drive_path("e") == "\\\\.\\E:"
    assert _windows_cdda_drive_path("\\\\.\\F:") == "\\\\.\\F:"


class _FakeKernel32:
    def __init__(self, *, max_chunk: int, fail_all: bool = False):
        self.max_chunk = max_chunk
        self.fail_all = fail_all
        self.successful_counts: list[int] = []
        self.rejected_counts: list[int] = []
        self.closed_handles: list[int] = []

    def CreateFileW(self, *_):
        return 123

    def DeviceIoControl(
        self,
        _handle,
        _ioctl,
        info_ptr,
        _info_size,
        _buffer,
        _buffer_size,
        bytes_returned_ptr,
        _overlapped,
    ):
        count = int(info_ptr._obj.SectorCount)
        if self.fail_all or count > self.max_chunk:
            self.rejected_counts.append(count)
            return False
        self.successful_counts.append(count)
        bytes_returned_ptr._obj.value = count * CDDA_SECTOR_SIZE
        return True

    def CloseHandle(self, handle):
        self.closed_handles.append(handle)
        return True


def test_windows_cdda_reader_uses_larger_initial_chunks(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    kernel32 = _FakeKernel32(max_chunk=WINDOWS_CDDA_INITIAL_READ_CHUNK_SECTORS)

    with _WindowsCddaReader("D:", kernel32=kernel32) as reader:
        chunks = list(reader.read_sectors(0, WINDOWS_CDDA_INITIAL_READ_CHUNK_SECTORS * 2))

    assert [len(chunk) // CDDA_SECTOR_SIZE for chunk in chunks] == [
        WINDOWS_CDDA_INITIAL_READ_CHUNK_SECTORS,
        WINDOWS_CDDA_INITIAL_READ_CHUNK_SECTORS,
    ]
    assert kernel32.successful_counts == [
        WINDOWS_CDDA_INITIAL_READ_CHUNK_SECTORS,
        WINDOWS_CDDA_INITIAL_READ_CHUNK_SECTORS,
    ]
    assert kernel32.rejected_counts == []
    assert kernel32.closed_handles == [123]


def test_windows_cdda_reader_falls_back_to_smaller_chunks(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    kernel32 = _FakeKernel32(max_chunk=WINDOWS_CDDA_FALLBACK_READ_CHUNK_SECTORS)

    with _WindowsCddaReader("D:", kernel32=kernel32) as reader:
        chunks = list(reader.read_sectors(0, WINDOWS_CDDA_INITIAL_READ_CHUNK_SECTORS))

    assert kernel32.rejected_counts == [WINDOWS_CDDA_INITIAL_READ_CHUNK_SECTORS]
    assert kernel32.successful_counts == [
        WINDOWS_CDDA_FALLBACK_READ_CHUNK_SECTORS,
        WINDOWS_CDDA_FALLBACK_READ_CHUNK_SECTORS,
        WINDOWS_CDDA_FALLBACK_READ_CHUNK_SECTORS,
        WINDOWS_CDDA_FALLBACK_READ_CHUNK_SECTORS,
        WINDOWS_CDDA_INITIAL_READ_CHUNK_SECTORS - (WINDOWS_CDDA_FALLBACK_READ_CHUNK_SECTORS * 4),
    ]
    assert sum(len(chunk) for chunk in chunks) == WINDOWS_CDDA_INITIAL_READ_CHUNK_SECTORS * CDDA_SECTOR_SIZE
    assert reader.using_fallback_chunk


def test_windows_cdda_reader_raises_when_fallback_chunk_fails(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    kernel32 = _FakeKernel32(max_chunk=0, fail_all=True)

    try:
        with _WindowsCddaReader("D:", kernel32=kernel32) as reader:
            list(reader.read_sectors(0, WINDOWS_CDDA_INITIAL_READ_CHUNK_SECTORS))
    except _WindowsCddaReadError:
        pass
    else:
        raise AssertionError("expected _WindowsCddaReadError")

    assert kernel32.rejected_counts == [
        WINDOWS_CDDA_INITIAL_READ_CHUNK_SECTORS,
        WINDOWS_CDDA_FALLBACK_READ_CHUNK_SECTORS,
    ]
    assert kernel32.closed_handles == [123]


def test_safe_path_component_strips_trailing_dots_and_spaces():
    # Windows silently drops trailing dots/spaces from file/dir names; two
    # albums named "Foo." and "Foo" would otherwise collide on the filesystem.
    assert safe_path_component("Album.") == "Album"
    assert safe_path_component("Album ") == "Album"
    assert safe_path_component("Album. . .") == "Album"


def test_safe_path_component_suffixes_windows_reserved_names():
    # Windows refuses to create files named after legacy device handles,
    # even on NTFS via Win32. An album literally titled "CON" or "NUL"
    # should not abort the whole rip with an OSError on mkdir.
    assert safe_path_component("CON") == "CON_"
    assert safe_path_component("nul") == "nul_"
    assert safe_path_component("COM1") == "COM1_"
    assert safe_path_component("LPT9") == "LPT9_"
    # Reserved-name handling applies to the stem only.
    assert safe_path_component("CON.flac") == "CON_.flac"
    # Non-reserved names that merely start with a reserved prefix are fine.
    assert safe_path_component("Console") == "Console"


def test_safe_path_component_returns_unknown_for_empty_input():
    assert safe_path_component("") == "Unknown"
    assert safe_path_component(" . . ") == "Unknown"
    assert safe_path_component(".") == "Unknown"
    assert safe_path_component("..") == "Unknown"


def test_format_extension_matches_selected_rip_format():
    assert format_extension("mp3") == ".mp3"
    assert format_extension("WAV") == ".wav"
    assert format_extension("unknown") == ".flac"


def test_unique_track_output_suffixes_duplicate_same_run_targets(tmp_path):
    track = TrackInfo(number=1, title="Intro")
    used = set()

    first = _unique_track_output(tmp_path, track, 1, ".flac", used)
    second = _unique_track_output(tmp_path, track, 1, ".flac", used)

    assert first.name == "01 - Intro.flac"
    assert second.name == "01 - Intro (2).flac"


def test_track_output_files_plans_duplicate_same_run_targets(tmp_path):
    tracks = [
        TrackInfo(number=1, title="Intro"),
        TrackInfo(number=1, title="Intro"),
    ]

    planned = track_output_files(tmp_path, tracks, 2, ".flac")

    assert [path.name for path in planned] == ["01 - Intro.flac", "01 - Intro (2).flac"]


def test_existing_target_files_uses_selected_rip_format(tmp_path):
    settings = Settings(rip_format="mp3")
    album = AlbumInfo(artist="Artist", album="Album")
    album.tracks = [TrackInfo(number=1, title="Song")]
    flac = target_file(tmp_path, album.tracks[0], 1, ".flac")
    mp3 = target_file(tmp_path, album.tracks[0], 1, ".mp3")
    flac.write_bytes(b"old flac")

    assert _existing_target_files(settings, album, tmp_path) == []

    mp3.write_bytes(b"old mp3")
    assert _existing_target_files(settings, album, tmp_path) == [mp3]


def test_existing_target_files_checks_duplicate_planned_names(tmp_path):
    settings = Settings(rip_format="flac")
    album = AlbumInfo(artist="Artist", album="Album")
    album.tracks = [
        TrackInfo(number=1, title="Intro"),
        TrackInfo(number=1, title="Intro"),
    ]
    duplicate = tmp_path / "01 - Intro (2).flac"
    duplicate.write_bytes(b"old duplicate")

    assert _existing_target_files(settings, album, tmp_path) == [duplicate]


def test_ripper_track_rows_do_not_resize_status_column_per_row(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(ripper_view_module.cd_detect, "list_cd_drives", lambda: [])
    settings = Settings(music_root=str(tmp_path))
    view = RipperView(settings, object())
    calls: list[tuple[int, int]] = []

    class Header:
        def resizeSection(self, section: int, width: int) -> None:
            calls.append((section, width))

    monkeypatch.setattr(view.tracks, "horizontalHeader", lambda: Header())

    view._populate_default_tracks(4)

    assert view.tracks_model.rowCount() == 4
    assert calls == []


def test_soft_album_duplicate_cancel_disables_rip_button(qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(ripper_view_module.cd_detect, "list_cd_drives", lambda: [])
    monkeypatch.setattr(
        ripper_view_module.QMessageBox,
        "question",
        lambda *_args, **_kwargs: ripper_view_module.QMessageBox.No,
    )

    class FakeLibrary:
        def find_album_match(self, *_args):
            return ("Artist", "Album")

    view = RipperView(Settings(music_root=str(tmp_path)), FakeLibrary())
    view._toc = DiscToc(drive="D:", discid="disc-123", track_count=1)
    album = AlbumInfo(artist="Artist", album="Album")
    album.tracks = [TrackInfo(number=1, title="Track 01")]

    view._apply_album(album)

    assert view._toc is None
    assert not view.start_btn.isEnabled()


def test_rip_request_reuses_detected_disc_toc(tmp_path):
    album = AlbumInfo(artist="Artist", album="Album")
    toc = DiscToc(
        drive="D:",
        track_count=2,
        track_offsets=[150, 15150],
        sectors=30150,
    )

    request = _rip_request_from_toc(toc, album, tmp_path)

    assert request.drive == "D:"
    assert request.album is album
    assert request.target_dir == tmp_path
    assert request.track_offsets == (150, 15150)
    assert request.leadout_sector == 30150
    assert request.track_numbers == ()


def test_rip_worker_filters_retry_tracks_without_shrinking_album_metadata(monkeypatch, tmp_path):
    album = AlbumInfo(artist="Artist", album="Album")
    album.tracks = [
        TrackInfo(number=1, title="First"),
        TrackInfo(number=2, title="Second"),
        TrackInfo(number=3, title="Third"),
    ]
    request = RipRequest(
        "D:",
        album,
        tmp_path,
        track_offsets=(150, 15150, 30150),
        leadout_sector=45150,
        track_numbers=(2,),
    )
    worker = RipWorker(
        Settings(download_artwork=False, ctdb_verify_rips=False),
        request,
    )
    ripped: list[tuple[int, str]] = []
    tag_calls: list[tuple[int, int, str]] = []
    finished: list[tuple[bool, str]] = []

    def fake_rip_track(self, ffmpeg, track_no, title, out, **_):
        ripped.append((track_no, out.name))
        out.write_bytes(b"audio")
        return None

    def fake_write_tags(path, tagged_album, track, artwork, **_kw):
        tag_calls.append((track.number, len(tagged_album.tracks), path.name))
        return True

    monkeypatch.setattr("lyon.core.ripper.find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr("lyon.core.ripper._ffmpeg_supports_demuxer", lambda *_: True)
    monkeypatch.setattr(RipWorker, "_rip_track", fake_rip_track)
    monkeypatch.setitem(
        sys.modules,
        "lyon.core.tagger",
        types.SimpleNamespace(write_tags=fake_write_tags),
    )
    worker.finished.connect(lambda ok, msg: finished.append((ok, msg)))

    worker.run()

    assert ripped == [(2, "02 - Second.flac")]
    assert tag_calls == [(2, 3, "02 - Second.flac")]
    assert finished[-1] == (True, "Rip complete.")


def test_rip_worker_reports_tag_failures_as_failed_not_finished(monkeypatch, tmp_path):
    album = AlbumInfo(artist="Artist", album="Album")
    album.tracks = [TrackInfo(number=1, title="First")]
    request = RipRequest(
        "D:",
        album,
        tmp_path,
        track_offsets=(150,),
        leadout_sector=15150,
    )
    worker = RipWorker(
        Settings(download_artwork=False, ctdb_verify_rips=False),
        request,
    )
    failed: list[tuple[int, str]] = []
    completed: list[tuple[int, str]] = []
    finished: list[tuple[bool, str]] = []

    def fake_rip_track(self, ffmpeg, track_no, title, out, **_):
        out.write_bytes(b"audio")
        return None

    monkeypatch.setattr("lyon.core.ripper.find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr("lyon.core.ripper._ffmpeg_supports_demuxer", lambda *_: True)
    monkeypatch.setattr(RipWorker, "_rip_track", fake_rip_track)
    monkeypatch.setitem(
        sys.modules,
        "lyon.core.tagger",
        types.SimpleNamespace(write_tags=lambda *_, **__: False),
    )
    worker.track_failed.connect(lambda n, reason: failed.append((n, reason)))
    worker.track_finished.connect(lambda n, path: completed.append((n, path)))
    worker.finished.connect(lambda ok, msg: finished.append((ok, msg)))

    worker.run()

    assert failed == [(1, "Track ripped but audio tags could not be written.")]
    assert completed == []
    assert finished[-1] == (False, "Rip finished with errors.")


def test_rip_worker_reuses_one_raw_reader_for_multiple_tracks(monkeypatch, tmp_path):
    album = AlbumInfo(artist="Artist", album="Album")
    album.tracks = [
        TrackInfo(number=1, title="First"),
        TrackInfo(number=2, title="Second"),
    ]
    request = RipRequest(
        "D:",
        album,
        tmp_path,
        track_offsets=(150, 15150),
        leadout_sector=30150,
    )
    worker = RipWorker(
        Settings(download_artwork=False, ctdb_verify_rips=False),
        request,
    )
    opened: list[str] = []
    closed: list[str] = []
    reader_ids: list[int] = []
    finished: list[tuple[bool, str]] = []

    class FakeReader:
        active_chunk_sectors = 75
        using_fallback_chunk = False

        def __init__(self, drive):
            self.drive = drive

        def __enter__(self):
            opened.append(self.drive)
            return self

        def close(self):
            closed.append(self.drive)

    def fake_run_windows(self, ffmpeg, track_no, out, codec_args, sector_span, *, raw_reader=None):
        reader_ids.append(id(raw_reader))
        out.write_bytes(b"audio")
        return None

    def fake_write_tags(*_, **__):
        return True

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("lyon.core.ripper.find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr("lyon.core.ripper._ffmpeg_supports_demuxer", lambda *_: False)
    monkeypatch.setattr("lyon.core.ripper._WindowsCddaReader", FakeReader)
    monkeypatch.setattr(RipWorker, "_run_windows_cdda_ffmpeg", fake_run_windows)
    monkeypatch.setitem(
        sys.modules,
        "lyon.core.tagger",
        types.SimpleNamespace(write_tags=fake_write_tags),
    )
    worker.finished.connect(lambda ok, msg: finished.append((ok, msg)))

    worker.run()

    assert opened == ["D:"]
    assert closed == ["D:"]
    assert len(reader_ids) == 2
    assert reader_ids[0] == reader_ids[1]
    assert finished[-1] == (True, "Rip complete.")


def test_libcdio_failure_summary_recommends_supported_ffmpeg():
    reason = _summarize_ffmpeg_failure(
        ["Unknown input format: 'libcdio'"],
        1,
    )

    assert "libcdio CD input format" in reason
    assert "compiled with libcdio/CDDA support" in reason


def test_rip_failure_log_includes_track_reason_command_and_output(tmp_path):
    album = AlbumInfo(artist="Artist", album="Album", date="1999")
    album.tracks = [TrackInfo(number=1, title="First Track")]
    request = RipRequest(
        drive="D:",
        album=album,
        target_dir=tmp_path,
        track_offsets=(150,),
        leadout_sector=15150,
    )
    failure = RipFailure(
        1,
        "First Track",
        tmp_path / "01 - First Track.flac",
        "ffmpeg does not recognize the libcdio CD input format.",
        [
            FfmpegAttemptFailure(
                ["ffmpeg", "-f", "libcdio", "-i", "D:"],
                1,
                "ffmpeg does not recognize the libcdio CD input format.",
                ["Unknown input format: 'libcdio'"],
            ),
        ],
    )

    path = _write_failure_log(
        tmp_path,
        request,
        "ffmpeg",
        [failure],
        message="Rip finished with errors.",
    )

    assert path is not None
    text = path.read_text(encoding="utf-8")
    assert "Sea Lyon Media Manager rip failure log" in text
    assert "Track 1: First Track" in text
    assert "Command:" in text
    assert "Unknown input format: 'libcdio'" in text
    assert "Leadout sector: 15150" in text


def test_second_unknown_album_uses_new_folder_without_overwriting(tmp_path):
    settings = Settings(music_root=str(tmp_path))
    album = AlbumInfo(artist="Unknown Artist", album="Unknown Album")
    album.tracks = [TrackInfo(number=1, title="Track 01")]
    first = target_folder(settings, album)
    first.mkdir(parents=True)
    (first / "01 - Track 01.flac").write_bytes(b"first rip")

    second = unique_target_folder(settings, album, create=True)

    assert second == first.with_name("Unknown Album (2)")
    assert second.exists()
    assert (first / "01 - Track 01.flac").read_bytes() == b"first rip"


def test_known_album_keeps_stable_folder_for_overwrite_confirmation(tmp_path):
    settings = Settings(music_root=str(tmp_path))
    album = AlbumInfo(artist="Artist", album="Album")
    first = target_folder(settings, album)
    first.mkdir(parents=True)
    (first / "01 - Song.flac").write_bytes(b"existing")

    assert unique_target_folder(settings, album) == first


def test_target_folder_rejects_symlink_escape_from_music_root(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    music_root = tmp_path / "music"
    music_root.mkdir()
    try:
        (music_root / "Artist").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        return

    settings = Settings(music_root=str(music_root))
    album = AlbumInfo(artist="Artist", album="Album")

    try:
        target_folder(settings, album)
    except ValueError as exc:
        assert "inside the music folder" in str(exc)
    else:
        raise AssertionError("target folder should reject symlink escape")
