from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from helper_methods.model_methods import _optional_float_list, _optional_int, _optional_int_or_none, _optional_str, _str_to_list

@dataclass(frozen=True)
class Song:
    title: str
    jamendo_id: str
    id: Optional[int] = None
    artist: Optional[str] = None
    genre: List[str] = None
    speed: int = 0
    bpm: int = 0
    bpm_confidence: int = 0
    beat_intervals: Optional[List[float]] = None
    audio_url: Optional[str] = None
    download_url: Optional[str] = None
    beat_intervals: Optional[List[float]] = None
    start_time: int = 0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Song":
        return cls(
            id=_optional_int_or_none(data.get("id")),
            title=str(data["title"]),
            jamendo_id=str(data["jamendo_id"]),
            artist=_optional_str(data.get("artist")),
            genre=_str_to_list(_optional_str(data.get("genre"))),
            speed=_optional_int(data.get("speed"), default=0),
            bpm=_optional_int(data.get("bpm"), default=0),
            bpm_confidence=_optional_int(data.get("bpm_confidence"), default=0),
            audio_url=_optional_str(data.get("audio_url")),
            download_url=_optional_str(data.get("download_url")),
            beat_intervals=_optional_float_list(data.get("beat_intervals")),
            start_time=_optional_int(data.get("start_time"))
        )

    def to_record(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "jamendo_id": self.jamendo_id,
            "artist": self.artist,
            "genre": self.genre,
            "speed": self.speed,
            "bpm": self.bpm,
            "bpm_confidence": self.bpm_confidence,
            "audio_url": self.audio_url,
            "download_url": self.download_url,
            "beat_intervals": self.beat_intervals,
            "start_time": self.start_time,
        }


