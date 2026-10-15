import asyncio
import contextlib
import logging
import time
from urllib.parse import quote

from .config import Settings
from .storage import SongStorage
from .models import Song

log = logging.getLogger(__name__)

CHUNK = 64 * 1024
RETRY_DELAY_S = 3


class PlayerService:
    """Крутит плейлист по кругу: папка -> ffmpeg (-re, mp3 192k) -> Icecast."""

    def __init__(self, settings: Settings, storage: SongStorage):
        self._storage = storage
        self._icecast_url = (
            f"icecast://source:{quote(settings.icecast_password, safe='')}"
            f"@{settings.icecast_host}:{settings.icecast_port}/{settings.icecast_mount}"
        )
        self._task: asyncio.Task | None = None
        self.current_song: Song | None = None
        self._started_at = 0.0

    @property
    def streaming(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def position_seconds(self) -> float:
        if not self.streaming or not self._started_at:
            return 0.0
        return time.monotonic() - self._started_at

    async def start_playlist(self) -> None:
        await self.stop_stream()
        self._task = asyncio.create_task(self._run())

    async def stop_stream(self) -> None:
        task, self._task = self._task, None
        self.current_song = None
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _run(self) -> None:
        last_key: str | None = None
        while True:
            songs = await asyncio.to_thread(self._safe_list)
            songs.sort(key=lambda s: s.fileKey)
            if not songs:
                log.warning("Playlist is empty, waiting for tracks...")
                await asyncio.sleep(RETRY_DELAY_S)
                continue

            idx = 0
            if last_key is not None:
                for i, s in enumerate(songs):
                    if s.fileKey == last_key:
                        idx = (i + 1) % len(songs)
                        break
            song = songs[idx]
            last_key = song.fileKey

            log.info("Playing next: %s", song.fileKey)
            self.current_song = song
            self._started_at = time.monotonic()
            try:
                await self._push(song)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning("Skipping unavailable track: %s", song.fileKey, exc_info=True)
            # ffmpeg упал мгновенно (Icecast недоступен и т.п.) — не крутим цикл вхолостую
            if time.monotonic() - self._started_at < 2:
                await asyncio.sleep(RETRY_DELAY_S)

    def _safe_list(self) -> list[Song]:
        try:
            return self._storage.list_songs()
        except Exception:
            log.warning("Could not list songs", exc_info=True)
            return []

    async def _push(self, song: Song) -> None:
        resp = await asyncio.to_thread(self._storage.open_song, song.fileKey)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-loglevel", "error", "-re", "-i", "pipe:0",
            "-vn", "-acodec", "libmp3lame", "-ab", "192k", "-ar", "44100",
            "-f", "mp3", "-content_type", "audio/mpeg", "-ice_name", song.fileKey,
            self._icecast_url,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            while True:
                chunk = await asyncio.to_thread(resp.read, CHUNK)
                if not chunk:
                    break
                proc.stdin.write(chunk)
                await proc.stdin.drain()  # с -re ffmpeg читает в realtime — это и есть темп эфира
            proc.stdin.close()
            await proc.wait()
        except (BrokenPipeError, ConnectionResetError):
            log.error("ffmpeg/Icecast closed the pipe for %s", song.fileKey)
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            resp.close()
