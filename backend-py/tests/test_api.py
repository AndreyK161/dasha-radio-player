import io

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.storage import SongNotFound, is_mp3, parse_filename
from app.models import Song


class FakeStorage:
    def __init__(self):
        self.files: dict[str, bytes] = {}

    def list_songs(self):
        return [Song(*parse_filename(k), 12.5, k) for k in sorted(self.files)]

    def upload_song(self, name, fileobj, size):
        self.files["songs/" + name] = fileobj.read()
        return "songs/" + name

    def delete_song(self, name):
        if "songs/" + name not in self.files:
            raise SongNotFound(name)
        del self.files["songs/" + name]


@pytest.fixture
def client(monkeypatch):
    settings = Settings("admin", "pw", "s" * 32, 900, 3600, "/tmp/x", "localhost", 8000, "stream", "hackme")
    fake = FakeStorage()
    monkeypatch.setattr("app.main.SongStorage", lambda s: fake)
    with TestClient(create_app(settings, autostart=False)) as c:
        c.fake = fake
        yield c


def login(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "pw"})
    assert r.status_code == 200
    return r.json()


def auth(tokens):
    return {"Authorization": f"Bearer {tokens['token']}"}


def test_parse_and_mp3_detection():
    assert parse_filename("songs/Title – Artist.mp3") == ("Title", "Artist")
    assert parse_filename("songs/Title - Artist.mp3") == ("Title", "Artist")
    assert parse_filename("songs/Solo.mp3") == ("Solo", "Unknown")
    assert is_mp3(b"ID3") and is_mp3(b"\xff\xfb\x90") and not is_mp3(b"RIFF")


def test_login_bad_credentials(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "no"})
    assert r.status_code == 401 and r.json() == {"error": "Invalid credentials"}
    assert client.post("/api/auth/login", json={}).status_code == 401


def test_protected_requires_token(client):
    assert client.get("/api/songs").status_code == 401
    assert client.get("/api/songs", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_refresh_flow_and_token_types(client):
    t = login(client)
    # refresh-токен нельзя использовать как access
    bad = {"Authorization": f"Bearer {t['refreshToken']}"}
    assert client.get("/api/songs", headers=bad).status_code == 401
    # access-токен нельзя использовать для refresh
    assert client.post("/api/auth/refresh", json={"refreshToken": t["token"]}).status_code == 401
    r = client.post("/api/auth/refresh", json={"refreshToken": t["refreshToken"]})
    assert r.status_code == 200 and {"token", "refreshToken"} <= r.json().keys()


def test_upload_list_delete(client):
    h = auth(login(client))
    mp3 = b"ID3" + b"\x00" * 100
    r = client.post("/api/songs/upload", headers=h, files={"file": ("Hey – Me.mp3", mp3)})
    assert r.json() == {"status": "uploaded", "objectName": "songs/Hey – Me.mp3"}
    songs = client.get("/api/songs", headers=h).json()
    assert songs[0]["songName"] == "Hey" and songs[0]["artist"] == "Me"
    assert set(songs[0]) == {"guid", "songName", "artist", "duration", "fileKey"}
    assert client.delete("/api/songs", headers=h, params={"objectName": "Hey – Me.mp3"}).json() == {"status": "deleted"}
    assert client.delete("/api/songs", headers=h, params={"objectName": "Hey – Me.mp3"}).status_code == 404


def test_upload_validation(client):
    h = auth(login(client))
    assert client.post("/api/songs/upload", headers=h, files={"file": ("a.txt", b"ID3")}).status_code == 400
    assert client.post("/api/songs/upload", headers=h, files={"file": ("a.mp3", b"RIFFxxxx")}).status_code == 400


def test_stream_status_public(client):
    r = client.get("/api/stream/status")
    assert r.json() == {"streaming": False, "currentSong": None, "positionSeconds": 0.0}
    assert client.get("/api/stream/current").status_code == 204
    assert client.post("/api/stream/stop").status_code == 401
