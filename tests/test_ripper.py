import importlib.util
import sys
import types


def _install_dependency_stubs() -> None:
    pyside = types.ModuleType("PySide6")
    qtcore = types.ModuleType("PySide6.QtCore")

    class _Signal:
        def __init__(self, *_, **__):
            pass

        def connect(self, *_):
            pass

        def emit(self, *_):
            pass

    class _QObject:
        def __init__(self, *_, **__):
            pass

        def moveToThread(self, *_):
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


_install_dependency_stubs()

from lyon.core.cd_detect import DiscToc  # noqa: E402
from lyon.core.metadata import AlbumInfo, TrackInfo  # noqa: E402
from lyon.core.ripper import (  # noqa: E402
    FfmpegAttemptFailure,
    RipFailure,
    RipRequest,
    _build_libcdio_track_command,
    _build_raw_cdda_ffmpeg_command,
    _ffmpeg_format_listing_has_demuxer,
    _parse_progress,
    _summarize_ffmpeg_failure,
    _track_sector_span,
    _windows_cdda_drive_path,
    _write_failure_log,
)
from lyon.ui.ripper_view import _rip_request_from_toc  # noqa: E402


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
        8,
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

    cmd = _build_raw_cdda_ffmpeg_command("ffmpeg", out, 5)

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
    assert "Lyon Music Manager rip failure log" in text
    assert "Track 1: First Track" in text
    assert "Command:" in text
    assert "Unknown input format: 'libcdio'" in text
    assert "Leadout sector: 15150" in text
