from __future__ import annotations

from lyon.core.metadata import AlbumInfo, TrackInfo
from lyon.core import tagger


class FakeFlac(dict):
    instances: list["FakeFlac"] = []

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self.saved = False
        self.pictures_cleared = False
        self.pictures = []
        FakeFlac.instances.append(self)

    def clear_pictures(self) -> None:
        self.pictures_cleared = True

    def add_picture(self, picture) -> None:
        self.pictures.append(picture)

    def save(self) -> None:
        self.saved = True


def test_write_flac_tags_writes_disc_metadata(monkeypatch, tmp_path):
    FakeFlac.instances.clear()
    monkeypatch.setattr(tagger, "FLAC", FakeFlac)
    album = AlbumInfo(
        artist="Album Artist",
        album="Album",
        tracks=[
            TrackInfo(number=1, title="Disc 1", disc_number=1),
            TrackInfo(number=1, title="Disc 2", artist="Guest", disc_number=2),
        ],
    )

    assert tagger.write_flac_tags(tmp_path / "track.flac", album, album.tracks[1], None)

    flac = FakeFlac.instances[0]
    assert flac["artist"] == "Guest"
    assert flac["albumartist"] == "Album Artist"
    assert flac["tracknumber"] == "1"
    assert flac["tracktotal"] == "2"
    assert flac["discnumber"] == "2"
    assert flac["disctotal"] == "2"
    assert flac.saved is True
