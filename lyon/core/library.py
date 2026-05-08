"""SQLite-backed music library."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from mutagen import File as MutagenFile

from .settings import app_data_dir

SUPPORTED_EXTS = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma"}

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
    artwork_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(album_artist, artist);
CREATE INDEX IF NOT EXISTS idx_tracks_album  ON tracks(album);
CREATE INDEX IF NOT EXISTS idx_tracks_title  ON tracks(title);
"""


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
    artwork_path: str | None = None

    @property
    def display_artist(self) -> str:
        return self.album_artist or self.artist or "Unknown Artist"


class Library:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (app_data_dir() / "library.db")
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------------ scan
    def scan_paths(self, roots: Iterable[str | os.PathLike]) -> int:
        """Walk the given roots and add new audio files. Returns count added."""
        added = 0
        for root in roots:
            root = Path(root)
            if not root.exists():
                continue
            for dirpath, _dirs, files in os.walk(root):
                for name in files:
                    ext = os.path.splitext(name)[1].lower()
                    if ext not in SUPPORTED_EXTS:
                        continue
                    full = os.path.join(dirpath, name)
                    if self.add_file(full):
                        added += 1
        self.conn.commit()
        return added

    def add_file(self, path: str | os.PathLike) -> bool:
        path = str(path)
        cur = self.conn.execute("SELECT 1 FROM tracks WHERE path = ?", (path,))
        if cur.fetchone():
            return False
        meta = _read_tags(path)
        if meta is None:
            return False
        # Look for adjacent cover art
        art = _find_local_artwork(Path(path).parent)
        self.conn.execute(
            """INSERT INTO tracks
               (path, title, artist, album_artist, album, track_no, disc_no,
                year, genre, duration, bitrate, samplerate, artwork_path)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
            ),
        )
        return True

    # ------------------------------------------------------------------ queries
    def all_artists(self) -> list[str]:
        rows = self.conn.execute(
            f"""SELECT DISTINCT {DISPLAY_ARTIST_SQL} AS a
                FROM tracks
                ORDER BY a COLLATE NOCASE"""
        ).fetchall()
        return [r["a"] for r in rows]

    def albums_for_artist(self, artist: str) -> list[tuple[str, str | None]]:
        rows = self.conn.execute(
            f"""SELECT {DISPLAY_ALBUM_SQL} AS display_album, MAX(artwork_path) AS art
                FROM tracks
                WHERE {DISPLAY_ARTIST_SQL} = ?
                GROUP BY display_album
                ORDER BY MIN(year), display_album COLLATE NOCASE""",
            (artist,),
        ).fetchall()
        return [(r["display_album"], r["art"]) for r in rows]

    def all_albums(self) -> list[tuple[str, str, str | None]]:
        rows = self.conn.execute(
            f"""SELECT {DISPLAY_ARTIST_SQL} AS a,
                       {DISPLAY_ALBUM_SQL} AS display_album, MAX(artwork_path) AS art
                FROM tracks
                GROUP BY a, display_album
                ORDER BY a COLLATE NOCASE, display_album COLLATE NOCASE"""
        ).fetchall()
        return [(r["a"], r["display_album"], r["art"]) for r in rows]

    def tracks_for_album(self, artist: str, album: str) -> list[Track]:
        rows = self.conn.execute(
            f"""SELECT * FROM tracks
                WHERE {DISPLAY_ARTIST_SQL} = ? AND {DISPLAY_ALBUM_SQL} = ?
                ORDER BY disc_no, track_no, title COLLATE NOCASE""",
            (artist, album),
        ).fetchall()
        return [_row_to_track(r) for r in rows]

    def search(self, query: str) -> list[Track]:
        like = f"%{query}%"
        rows = self.conn.execute(
            """SELECT * FROM tracks
               WHERE title LIKE ? OR artist LIKE ? OR album LIKE ?
               ORDER BY artist, album, track_no LIMIT 500""",
            (like, like, like),
        ).fetchall()
        return [_row_to_track(r) for r in rows]

    def all_tracks(self) -> Iterator[Track]:
        for r in self.conn.execute("SELECT * FROM tracks ORDER BY id"):
            yield _row_to_track(r)

    def remove_missing(self) -> int:
        n = 0
        for r in self.conn.execute("SELECT id, path FROM tracks").fetchall():
            if not Path(r["path"]).exists():
                self.conn.execute("DELETE FROM tracks WHERE id = ?", (r["id"],))
                n += 1
        self.conn.commit()
        return n


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
        artwork_path=r["artwork_path"],
    )


def _read_tags(path: str) -> dict | None:
    try:
        f = MutagenFile(path, easy=True)
    except Exception:
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
