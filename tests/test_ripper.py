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

        def wait(self, *_):
            pass

    qtgui = types.ModuleType("PySide6.QtGui")
    qtwidgets = types.ModuleType("PySide6.QtWidgets")

    class _Qt:
        AlignCenter = 1
        ElideRight = 1
        KeepAspectRatio = 1
        SmoothTransformation = 1

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
        "QLabel", "QLineEdit", "QProgressBar", "QPushButton",
        "QTableView", "QVBoxLayout", "QWidget",
    ):
        setattr(qtwidgets, name, _Widget)
    qtwidgets.QMessageBox = _QMessageBox
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
from lyon.core.metadata import AlbumInfo  # noqa: E402
from lyon.core.ripper import (  # noqa: E402
    RipRequest,
    RipWorker,
    _build_cdda_track_command,
    _build_libcdio_track_command,
    _track_sector_span,
)
from lyon.core.settings import Settings  # noqa: E402
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
    assert "-nostdin" in cmd
    assert "-stats" not in cmd
    assert "0:a:1" not in cmd
    assert cmd[-1] == str(out)


def test_cdda_command_addresses_a_single_track(tmp_path):
    out = tmp_path / "track.flac"

    cmd = _build_cdda_track_command("ffmpeg", "D:\\", out, 5, 3)

    assert cmd[cmd.index("-i") + 1] == "cdda://D:?track=3"
    assert "-nostdin" in cmd
    assert "-vn" in cmd
    assert cmd[-1] == str(out)


def test_rip_track_tries_direct_cdda_after_toc_slicing_fails(tmp_path):
    album = AlbumInfo(artist="Artist", album="Album")
    request = RipRequest(
        drive="D:",
        album=album,
        target_dir=tmp_path,
        track_offsets=(150, 15150),
        leadout_sector=30150,
    )
    worker = RipWorker(Settings(), request)
    seen: list[list[str]] = []

    def fake_run(cmd: list[str], _track_no: int, _out):
        seen.append(cmd)
        return cmd[cmd.index("-i") + 1].startswith("cdda://")

    worker._run_ffmpeg = fake_run

    assert worker._rip_track("ffmpeg", 1, tmp_path / "track.flac") is True
    assert len(seen) == 3
    assert seen[-1][seen[-1].index("-i") + 1] == "cdda://D:?track=1"


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


def test_target_file_includes_disc_number_for_later_discs(tmp_path):
    from lyon.core.metadata import TrackInfo
    from lyon.core.ripper import target_file

    track = TrackInfo(number=1, title="Intro", disc_number=2)

    assert target_file(tmp_path, track, total=12).name == "2-01 - Intro.flac"


def test_artwork_file_name_matches_png_signature():
    from lyon.core.ripper import artwork_file_name

    assert artwork_file_name(b"\x89PNG\r\n\x1a\nrest") == "cover.png"
    assert artwork_file_name(b"\xff\xd8\xffrest") == "cover.jpg"


def test_edited_track_info_preserves_lookup_metadata_after_title_edit():
    from lyon.core.metadata import TrackInfo
    from lyon.ui.ripper_view import _edited_track_info

    original = TrackInfo(
        number=1,
        title="Original",
        length_ms=123000,
        artist="Guest Artist",
        disc_number=2,
    )

    edited = _edited_track_info(original, "3", "Edited Title", 1, "Album Artist")

    assert edited.number == 3
    assert edited.title == "Edited Title"
    assert edited.length_ms == 123000
    assert edited.artist == "Guest Artist"
    assert edited.disc_number == 2


def test_edited_track_info_falls_back_for_manual_rows():
    from lyon.ui.ripper_view import _edited_track_info

    edited = _edited_track_info(None, "bad", "", 4, "Album Artist")

    assert edited.number == 4
    assert edited.title == "Track 04"
    assert edited.artist == "Album Artist"
    assert edited.disc_number == 1
