from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class AudioAnalysis:
    bpm: float
    confidence: float
    beats: Optional[List[float]] = None
    bpm_estimates: Optional[List[float]] = None
    beat_intervals: Optional[List[float]] = None