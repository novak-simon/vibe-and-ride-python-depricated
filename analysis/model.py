from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class AudioAnalysis:
    bpm: float
    bpm_confidence: Optional[float]
    beats: List[float]
    beat_intervals: List[float]

    def to_record(self) -> Dict[str, Any]:
        return {
            "bpm": self.bpm,
            "bpm_confidence": self.bpm_confidence,
            "beats": self.beats,
            "beat_intervals": self.beat_intervals,
        }