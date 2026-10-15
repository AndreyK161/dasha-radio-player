import os
from dataclasses import dataclass


def _env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Environment variable {name} is required")
    return value


@dataclass(frozen=True)
class Settings:
    admin_username: str
    admin_password: str
    jwt_secret: str
    jwt_expiration_s: int
    jwt_refresh_expiration_s: int
    songs_dir: str
    icecast_host: str
    icecast_port: int
    icecast_mount: str
    icecast_password: str
    max_upload_bytes: int = 50 * 1024 * 1024


def load_settings() -> Settings:
    return Settings(
        admin_username=_env("ADMIN_USERNAME"),
        admin_password=_env("ADMIN_PASSWORD"),
        jwt_secret=_env("JWT_SECRET"),
        jwt_expiration_s=900,
        jwt_refresh_expiration_s=604800,
        songs_dir=_env("SONGS_DIR", "/data/songs"),
        icecast_host=_env("ICECAST_HOST", "localhost"),
        icecast_port=int(_env("ICECAST_PORT", "8000")),
        icecast_mount=_env("ICECAST_MOUNT", "stream"),
        icecast_password=_env("ICECAST_SOURCE_PASSWORD", "hackme"),
    )
