"""SQLite-backed music library."""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator

from mutagen import File as MutagenFile

from .settings import app_data_dir

LOG = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTS = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma"}
SUPPORTED_VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov"}
SUPPORTED_EXTS = SUPPORTED_AUDIO_EXTS | SUPPORTED_VIDEO_EXTS

DISPLAY_ARTIST_SQL = "COALESCE(NULLIF(album_artist,''), NULLIF(artist,''), 'Unknown Artist')"
DISPLAY_ALBUM_SQL = "COALESCE(NULLIF(album,''), 'Unknown Album')"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    title TEXT,
    artist TEXT,
    album_artist TEXT,
    album TEXT,
    track_no INTEGER,
    disc_no INTEGER,
    year INTEGER,
    genre TEXT,
    duration REAL,
    bitrate INTEGER,
    samplerate INTEGER,
    added_at REAL DEFAULT (strftime('%s','now')),
    artwork_path TEXT,
    media_type TEXT NOT NULL DEFAULT 'audio',
    disc_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_tracks_artist  ON tracks(album_artist, artist);
CREATE INDEX IF NOT EXISTS idx_tracks_album   ON tracks(album);
CREATE INDEX IF NOT EXISTS idx_tracks_title   ON tracks(title);
CREATE INDEX IF NOT EXISTS idx_tracks_media_type ON tracks(media_type);
CREATE INDEX IF NOT EXISTS idx_tracks_disc_id ON tracks(disc_id);
"""

_PAGE_SIZE = 500  # rows per page in streaming queries


@dataclass
class Track:
    id: int
    path: str
    title: str
    artist: str
    album_artist: str
    album: str
    track_no: int
    disc_no: int
    year: int
    genre: str
    duration: float
    bitrate: int = 0
    samplerate: int = 0
    artwork_path: str | None = None
    media_type: str = "audio"

    @property
    def display_artist(self) -> str:
        return self.album_artist or self.artist or "Unknown Artist"

    @property
    def is_video(self) -> bool:
        return self.media_type == "video"


class Library:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (app_data_dir() / "library.db")
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.executescript(SCHEMA)
            self._migrate()
            self.conn.commit()

    def _migrate(self) -> None:
        """Add columns that were introduced after initial release."""
        try:
            self.conn.execute(
                "ALTER TABLE tracks ADD COLUMN media_type TEXT NOT NULL DEFAULT 'audio'"
            )
        except sqlite3.OperationalError:
            pass  # column already exists
        try:
            self.conn.execute("ALTER TABLE tracks ADD COLUMN disc_id TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tracks_disc_id ON tracks(disc_id)"
        )

    def commit(self) -> None:
        with self._lock:
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def __enter__(self) -> "Library":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ------------------------------------------------------------------ scan
    def scan_paths(
        self,
        roots: Iterable[str | os.PathLike],
        should_cancel: "Callable[[], bool] | None" = None,
    ) -> int:
        """Walk the given roots and add new audio/video files. Returns count added.

        ``should_cancel`` is checked inside the directory walk; when it
        returns True the scan commits whatever has been added so far and
        returns early. This lets callers (typically a worker QThread) get
        out cleanly when the user closes the app mid-scan.
        """
        added = 0
        for root in roots:
            root = Path(root)
            if not root.exists():
                continue
            for dirpath, _dirs, files in os.walk(root):
                if should_cancel is not None and should_cancel():
                    with self._lock:
                        self.conn.commit()
                    return added
                for name in files:
                    ext = os.path.splitext(name)[1].lower()
                    if ext not in SUPPORTED_EXTS:
                        continue
                    full = os.path.join(dirpath, name)
                    if self.add_file(full):
                        added += 1
        with self._lock:
            self.conn.commit()
        return added

    def add_file(self, path: str | os.PathLike, disc_id: str | None = None) -> bool:
        path = str(path)
        ext = Path(path).suffix.lower()
        media_type = "video" if ext in SUPPORTED_VIDEO_EXTS else "audio"

        with self._lock:
            if self.conn.execute("SELECT 1 FROM tracks WHERE path = ?", (path,)).fetchone():
                return False
        meta = _read_tags(path)
        if meta is None:
            if media_type == "video":
                meta = {
                    "title": Path(path).stem,
                    "artist": "", "album_artist": "", "album": "",
                    "track_no": 0, "disc_no": 1, "year": 0, "genre": "",
                    "duration": 0.0, "bitrate": 0, "samplerate": 0,
                }
            else:
                return False
        # Look for adjacent cover art
        art = _find_local_artwork(Path(path).parent)
        with self._lock:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO tracks
                   (path, title, artist, album_artist, album, track_no, disc_no,
                    year, genre, duration, bitrate, samplerate, artwork_path, media_type,
                    disc_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    path,
                    meta["title"],
                    meta["artist"],
                    meta["album_artist"],
                    meta["album"],
                    meta["track_no"],
                    meta["disc_no"],
                    meta["year"],
                    meta["genre"],
                    meta["duration"],
                    meta["bitrate"],
                    meta["samplerate"],
                    str(art) if art else None,
                    media_type,
                    disc_id or None,
                ),
            )
            return cur.rowcount > 0

    # ------------------------------------------------------------------ queries
    def all_artists(self, media_type: str | None = None) -> list[str]:
        filter_sql = "" if media_type is None else "AND media_type = ?"
        params = () if media_type is None else (media_type,)
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT DISTINCT {DISPLAY_ARTIST_SQL} AS a
                    FROM tracks
                    WHERE 1=1 {filter_sql}
                    ORDER BY a COLLATE NOCASE""",
                params,
            ).fetchall()
        return [r["a"] for r in rows]

    def albums_for_artist(
        self, artist: str, media_type: str | None = None
    ) -> list[tuple[str, str | None]]:
        filter_sql = "" if media_type is None else "AND media_type = ?"
        params = (artist, media_type) if media_type is not None else (artist,)
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT {DISPLAY_ALBUM_SQL} AS display_album, MAX(artwork_path) AS art
                    FROM tracks
                    WHERE {DISPLAY_ARTIST_SQL} = ? {filter_sql}
                    GROUP BY display_album
                    ORDER BY MIN(year), display_album COLLATE NOCASE""",
                params,
            ).fetchall()
        return [(r["display_album"], r["art"]) for r in rows]

    def all_albums(self) -> list[tuple[str, str, str | None]]:
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT {DISPLAY_ARTIST_SQL} AS a,
                           {DISPLAY_ALBUM_SQL} AS display_album, MAX(artwork_path) AS art
                    FROM tracks
                    GROUP BY a, display_album
                    ORDER BY a COLLATE NOCASE, display_album COLLATE NOCASE"""
            ).fetchall()
        return [(r["a"], r["display_album"], r["art"]) for r in rows]

    def tracks_for_album(
        self, artist: str, album: str, media_type: str | None = None
    ) -> list[Track]:
        filter_sql = "" if media_type is None else "AND media_type = ?"
        params = (artist, album, media_type) if media_type is not None else (artist, album)
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT * FROM tracks
                    WHERE {DISPLAY_ARTIST_SQL} = ? AND {DISPLAY_ALBUM_SQL} = ? {filter_sql}
                    ORDER BY disc_no, track_no, title COLLATE NOCASE""",
                params,
            ).fetchall()
        return [_row_to_track(r) for r in rows]

    def search(self, query: str, media_type: str | None = None) -> list[Track]:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{escaped}%"
        filter_sql = "" if media_type is None else "AND media_type = ?"
        base_params = (like, like, like, like, like, like)
        params = base_params + (media_type,) if media_type is not None else base_params
        with self._lock:
            rows = self.conn.execute(
                f"""SELECT * FROM tracks
                   WHERE (title LIKE ? ESCAPE '\\'
                      OR artist LIKE ? ESCAPE '\\'
                      OR album_artist LIKE ? ESCAPE '\\'
                      OR album LIKE ? ESCAPE '\\'
                      OR {DISPLAY_ARTIST_SQL} LIKE ? ESCAPE '\\'
                      OR {DISPLAY_ALBUM_SQL} LIKE ? ESCAPE '\\')
                   {filter_sql}
                   ORDER BY {DISPLAY_ARTIST_SQL}, {DISPLAY_ALBUM_SQL}, disc_no, track_no
                   LIMIT 500""",
                params,
            ).fetchall()
        return [_row_to_track(r) for r in rows]

    def all_tracks(self, media_type: str | None = None) -> Iterator[Track]:
        """Yield every track in id order, paging to avoid loading the full table at once."""
        filter_sql = "" if media_type is None else "AND media_type = ?"
        params_base = (media_type,) if media_type is not None else ()
        offset = 0
        while True:
            params = params_base + (_PAGE_SIZE, offset)
            with self._lock:
                rows = self.conn.execute(
                    f"SELECT * FROM tracks WHERE 1=1 {filter_sql} ORDER BY id LIMIT ? OFFSET ?",
                    params,
                ).fetchall()
            if not rows:
                break
            for r in rows:
                yield _row_to_track(r)
            if len(rows) < _PAGE_SIZE:
                break
            offset += len(rows)

    def has_disc(self, disc_id: str, min_tracks: int = 1) -> bool:
        """Return True if at least *min_tracks* library tracks carry this disc ID."""
        if not disc_id:
            return False
        with self._lock:
            count = self.conn.execute(
                "SELECT COUNT(*) FROM tracks WHERE disc_id = ?", (disc_id,)
            ).fetchone()[0]
        return count >= min_tracks

    def album_for_disc(self, disc_id: str) -> tuple[str, str] | None:
        """Return (display_artist, album) for the first track carrying this disc ID, or None."""
        with self._lock:
            row = self.conn.execute(
                f"SELECT {DISPLAY_ARTIST_SQL} AS a, {DISPLAY_ALBUM_SQL} AS b"
                " FROM tracks WHERE disc_id = ? LIMIT 1",
                (disc_id,),
            ).fetchone()
        return (row["a"], row["b"]) if row else None

    def remove_missing(self) -> int:
        with self._lock:
            rows = self.conn.execute("SELECT id, path FROM tracks").fetchall()
        # Path existence checks run outside the lock to avoid blocking queries.
        missing_ids = [r["id"] for r in rows if not Path(r["path"]).exists()]
        if not missing_ids:
            return 0
        with self._lock:
            self.conn.executemany(
                "DELETE FROM tracks WHERE id = ?", [(id_,) for id_ in missing_ids]
            )
            self.conn.commit()
        return len(missing_ids)


def _row_to_track(r: sqlite3.Row) -> Track:
    return Track(
        id=r["id"],
        path=r["path"],
        title=r["title"] or Path(r["path"]).stem,
        artist=r["artist"] or "",
        album_artist=r["album_artist"] or "",
        album=r["album"] or "",
        track_no=r["track_no"] or 0,
        disc_no=r["disc_no"] or 0,
        year=r["year"] or 0,
        genre=r["genre"] or "",
        duration=r["duration"] or 0.0,
        bitrate=r["bitrate"] or 0,
        samplerate=r["samplerate"] or 0,
        artwork_path=r["artwork_path"],
        media_type=r["media_type"] if r["media_type"] else "audio",
    )


def _read_tags(path: str) -> dict | None:
    try:
        f = MutagenFile(path, easy=True)
    except Exception as exc:
        LOG.warning("Failed to read tags from %s: %s", path, exc)
        return None
    if f is None:
        return None
    info = getattr(f, "info", None)
    def first(key: str) -> str:
        v = f.get(key)
        if isinstance(v, list) and v:
            return str(v[0])
        return ""
    def to_int(s: str) -> int:
        if not s:
            return 0
        s = s.split("/")[0].strip()
        try:
            return int(s)
        except ValueError:
            try:
                return int(s[:4])
            except ValueError:
                return 0
    return {
        "title": first("title") or Path(path).stem,
        "artist": first("artist"),
        "album_artist": first("albumartist") or first("artist"),
        "album": first("album"),
        "track_no": to_int(first("tracknumber")),
        "disc_no": to_int(first("discnumber")) or 1,
        "year": to_int(first("date") or first("year")),
        "genre": first("genre"),
        "duration": float(getattr(info, "length", 0.0) or 0.0),
        "bitrate": int(getattr(info, "bitrate", 0) or 0),
        "samplerate": int(getattr(info, "sample_rate", 0) or 0),
    }


def _find_local_artwork(folder: Path) -> Path | None:
    for name in ("cover.jpg", "cover.png", "folder.jpg", "folder.png", "front.jpg"):
        p = folder / name
        if p.exists():
            return p
    return None
