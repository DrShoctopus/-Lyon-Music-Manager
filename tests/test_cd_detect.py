from lyon.core.cd_detect import (
    _CtdbTocEntry,
    _ctdb_entries_from_windows_toc,
    _ctdb_toc_from_track_data,
    _disc_toc_from_ctdb_entries,
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
            _track_data(2, 0x40, 15000),
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
