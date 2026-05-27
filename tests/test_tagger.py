from mutagen.mp4 import MP4FreeForm

from lyon.core.metadata import AlbumInfo, TrackInfo
from lyon.core.tagger import write_tags


def test_write_tags_writes_m4a_disc_id_with_supported_freeform_format(tmp_path, monkeypatch):
    created = []

    class FakeMP4(dict):
        def __init__(self, _path):
            super().__init__()
            self.saved = False
            created.append(self)

        def save(self):
            self.saved = True

    monkeypatch.setattr("mutagen.mp4.MP4", FakeMP4)
    album = AlbumInfo(artist="Artist", album="Album")
    track = TrackInfo(number=1, title="Track 01")
    album.tracks = [track]

    result = write_tags(
        tmp_path / "track01.m4a",
        album,
        track,
        artwork=None,
        disc_id="disc-123",
    )

    assert result is True
    audio = created[0]
    value = audio["----:com.apple.iTunes:MusicBrainz Disc Id"][0]
    assert isinstance(value, MP4FreeForm)
    assert bytes(value) == b"disc-123"
    assert value.dataformat == MP4FreeForm.FORMAT_TEXT
    assert audio.saved is True
