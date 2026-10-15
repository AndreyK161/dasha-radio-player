import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .auth import AdminOnly, JwtService, credentials_match
from .config import Settings, load_settings
from .storage import SongNotFound, SongStorage, is_mp3
from .player import PlayerService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class LoginBody(BaseModel):
    username: str | None = None
    password: str | None = None


class RefreshBody(BaseModel):
    refreshToken: str | None = None


def create_app(settings: Settings | None = None, *, autostart: bool = True) -> FastAPI:
    settings = settings or load_settings()
    minio = SongStorage(settings)
    player = PlayerService(settings, minio)
    jwt_service = JwtService(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if autostart:
            await player.start_playlist()
        yield
        await player.stop_stream()

    app = FastAPI(title="dasha.", lifespan=lifespan)
    app.state.jwt = jwt_service

    @app.exception_handler(HTTPException)
    async def http_error(_, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    # ── auth ──────────────────────────────────────────────────────────────
    @app.post("/api/auth/login")
    def login(body: LoginBody):
        if credentials_match(settings.admin_username, body.username) and \
                credentials_match(settings.admin_password, body.password):
            return {
                "token": jwt_service.generate_token(body.username),
                "refreshToken": jwt_service.generate_refresh_token(body.username),
            }
        raise HTTPException(401, "Invalid credentials")

    @app.post("/api/auth/refresh")
    def refresh(body: RefreshBody):
        claims = jwt_service.decode(body.refreshToken) if body.refreshToken else None
        if claims is None or claims.get("type") != "refresh":
            raise HTTPException(401, "Invalid refresh token")
        user = claims["sub"]
        return {
            "token": jwt_service.generate_token(user),
            "refreshToken": jwt_service.generate_refresh_token(user),
        }

    # ── songs ─────────────────────────────────────────────────────────────
    @app.get("/api/songs", dependencies=[AdminOnly])
    def get_songs():
        return minio.list_songs()

    @app.post("/api/songs/upload", dependencies=[AdminOnly])
    def upload_song(file: UploadFile = File(...)):
        name = os.path.basename(file.filename or "")
        if not name.lower().endswith(".mp3"):
            raise HTTPException(400, "Only .mp3 files are allowed")
        if not is_mp3(file.file.read(3)):
            raise HTTPException(400, "File content is not a valid MP3")
        file.file.seek(0, os.SEEK_END)
        size = file.file.tell()
        if size > settings.max_upload_bytes:
            raise HTTPException(413, "File too large")
        file.file.seek(0)
        key = minio.upload_song(name, file.file, size)
        return {"status": "uploaded", "objectName": key}

    @app.delete("/api/songs", dependencies=[AdminOnly])
    def delete_song(objectName: str = Query(...)):
        current = player.current_song
        if current and current.fileKey == "songs/" + objectName:
            raise HTTPException(409, "Трек сейчас играет в эфире")
        try:
            minio.delete_song(objectName)
        except SongNotFound:
            raise HTTPException(404, "Song not found")
        return {"status": "deleted"}

    # ── stream ────────────────────────────────────────────────────────────
    @app.post("/api/stream/play-all", dependencies=[AdminOnly])
    async def play_all():
        await player.start_playlist()
        return {"status": "streaming", "mode": "playlist"}

    @app.post("/api/stream/stop", dependencies=[AdminOnly])
    async def stop():
        await player.stop_stream()
        return {"status": "stopped"}

    @app.get("/api/stream/status")
    def status():
        return {
            "streaming": player.streaming,
            "currentSong": player.current_song,
            "positionSeconds": player.position_seconds,
        }

    @app.get("/api/stream/current")
    def current():
        song = player.current_song
        return song if song else Response(status_code=204)

    return app
