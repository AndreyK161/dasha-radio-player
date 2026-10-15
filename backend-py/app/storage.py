import logging
import os
import shutil
import subprocess
from pathlib import Path

from .config import Settings
from .models import Song

log = logging.getLogger(__name__)

SONGS_PREFIX = "songs/"


def parse_filename(object_name: str) -> tuple[str, str]:
    """'songs/Title – Artist.mp3' -> ('Title', 'Artist')."""
    name = object_name[len(SONGS_PREFIX):].removesuffix(".mp3")
    # разделитель: " – " (среднее тире) или обычный " - "
    title, _, artist = name.replace(" - ", " – ").partition(" – ")
    return title.strip(), artist.strip() or "Unknown"


def is_mp3(head: bytes) -> bool:
    if head[:3] == b"ID3":
        return True
    return len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0


class SongNotFound(Exception):
    pass


class SongStorage:
    """Треки лежат в обычной папке на диске. fileKey остаётся 'songs/<имя>.mp3'."""

    def __init__(self, settings: Settings):
        self._dir = Path(settings.songs_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._durations: dict[str, float | None] = {}

    def _path(self, filename: str) -> Path:
        path = (self._dir / filename).resolve()
        if path.parent != self._dir.resolve():
            raise SongNotFound(filename)
        return path

    def list_songs(self) -> list[Song]:
        songs = []
        for path in sorted(self._dir.glob("*.mp3")):
            key = SONGS_PREFIX + path.name
            if key not in self._durations:
                self._durations[key] = self._fetch_duration(path)
            title, artist = parse_filename(key)
            songs.append(Song(title, artist, self._durations[key], key))
        return songs

    @staticmethod
    def _fetch_duration(path: Path) -> float | None:
        try:
            out = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", "-i", str(path)],
                capture_output=True, text=True, timeout=30,
            ).stdout.strip()
            return None if not out or out == "N/A" else float(out)
        except Exception:
            log.warning("Could not fetch duration for %s", path, exc_info=True)
            return None

    def upload_song(self, filename: str, fileobj, size: int) -> str:
        path = self._path(filename)
        tmp = path.with_suffix(".part")
        with open(tmp, "wb") as out:
            shutil.copyfileobj(fileobj, out)
        os.replace(tmp, path)  # атомарно: плеер не увидит недописанный файл
        self._durations.pop(SONGS_PREFIX + filename, None)
        return SONGS_PREFIX + filename

    def delete_song(self, filename: str) -> None:
        path = self._path(filename)
        if not path.is_file():
            raise SongNotFound(filename)
        path.unlink()
        self._durations.pop(SONGS_PREFIX + filename, None)

    def open_song(self, key: str):
        return open(self._path(key.removeprefix(SONGS_PREFIX)), "rb")
