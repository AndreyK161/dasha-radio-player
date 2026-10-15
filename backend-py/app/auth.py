import hmac
import time

import jwt
from fastapi import Depends, HTTPException, Request

from .config import Settings


class JwtService:
    def __init__(self, settings: Settings):
        self._secret = settings.jwt_secret
        self._ttl = settings.jwt_expiration_s
        self._refresh_ttl = settings.jwt_refresh_expiration_s

    def _build(self, username: str, ttl: int, kind: str) -> str:
        now = int(time.time())
        return jwt.encode(
            {"sub": username, "type": kind, "iat": now, "exp": now + ttl},
            self._secret,
            algorithm="HS256",
        )

    def generate_token(self, username: str) -> str:
        return self._build(username, self._ttl, "access")

    def generate_refresh_token(self, username: str) -> str:
        return self._build(username, self._refresh_ttl, "refresh")

    def decode(self, token: str) -> dict | None:
        try:
            return jwt.decode(token, self._secret, algorithms=["HS256"])
        except jwt.PyJWTError:
            return None


def credentials_match(expected: str, given: str | None) -> bool:
    return given is not None and hmac.compare_digest(expected.encode(), given.encode())


def require_admin(request: Request) -> str:
    jwt_service: JwtService = request.app.state.jwt
    header = request.headers.get("Authorization", "")
    claims = jwt_service.decode(header[7:]) if header.startswith("Bearer ") else None
    if claims is None or claims.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return claims["sub"]


AdminOnly = Depends(require_admin)
