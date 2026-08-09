from __future__ import annotations

import numpy as np
import librosa
from typing import List, Optional

from .model import AudioAnalysis


class LibrosaAnalyzer:
    """
    Analyze a local audio file using librosa beat tracking.

    The BPM confidence is an application-level metric based on beat-interval
    regularity; this is not a librosa-provided confidence score.
    """

    def analyze(self, audio_path: str) -> AudioAnalysis:
        y, sr = librosa.load(audio_path, sr=None, mono=True)
        if y.size == 0:
            raise ValueError(f"Unable to decode audio from {audio_path}")

        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        for temp in tempo:
            bpm = float(temp)

        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        beats = [float(value) for value in beat_times]
        beat_intervals = [
            float(beats[i + 1] - beats[i]) for i in range(len(beats) - 1)
        ]

        return AudioAnalysis(
            bpm=bpm,
            bpm_confidence=self._confidence_for_intervals(beat_intervals),
            beats=beats,
            beat_intervals=beat_intervals,
        )

    @staticmethod
    def _confidence_for_intervals(intervals: List[float]) -> Optional[float]:
        if len(intervals) < 2:
            return None

        mean_interval = float(np.mean(intervals))
        if mean_interval <= 0:
            return None

        std_interval = float(np.std(intervals, ddof=0))
        coefficient_of_variation = std_interval / mean_interval
        confidence = 1.0 - coefficient_of_variation
        return max(0.0, min(1.0, confidence))