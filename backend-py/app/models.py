import uuid
from dataclasses import dataclass, field


@dataclass
class Song:
    songName: str
    artist: str
    duration: float | None
    fileKey: str
    guid: str = field(default_factory=lambda: str(uuid.uuid4()))
