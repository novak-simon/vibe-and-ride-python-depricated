from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class Song:
    title: str
    jamendo_id: str
    id: Optional[int] = None
    artist: Optional[str] = None
    genre: Optional[str] = None
    speed: int = 0
    bpm: int = 0
    bpm_confidence: int = 0
    audio_url: Optional[str] = None
    download_url: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Song":
        return cls(
            id=_optional_int_or_none(data.get("id")),
            title=str(data["title"]),
            jamendo_id=str(data["jamendo_id"]),
            artist=_optional_str(data.get("artist")),
            genre=_optional_str(data.get("genre")),
            speed=_optional_int(data.get("speed"), default=0),
            bpm=_optional_int(data.get("bpm"), default=0),
            bpm_confidence=_optional_int(data.get("bpm_confidence"), default=0),
            audio_url=_optional_str(data.get("audio_url")),
            download_url=_optional_str(data.get("download_url")),
        )

    def to_record(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "artist": self.artist,
            "jamendo_id": self.jamendo_id,
            "genre": self.genre,
            "speed": self.speed,
            "bpm": self.bpm,
            "bpm_confidence": self.bpm_confidence,
            "audio_url": self.audio_url,
            "download_url": self.download_url,
        }


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)


def _optional_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    return int(value)


def _optional_int_or_none(value: Any) -> Optional[int]:
    if value is None:
        return None
    return int(value)