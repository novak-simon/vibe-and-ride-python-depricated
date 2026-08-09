from __future__ import annotations

import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from analysis.model import AudioAnalysis
from music.model import Song

try:
    from essentia import MonoLoader, RhythmExtractor2013
except ImportError as exc:
    MonoLoader = RhythmExtractor2013 = None
    _ESSENTIA_IMPORT_ERROR = exc


def _is_remote_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"}


def _download_remote_audio(url: str) -> Path:
    fd, filepath = tempfile.mkstemp(suffix=Path(urlparse(url).path).suffix or ".mp3")
    os.close(fd)
    try:
        with urllib.request.urlopen(url) as response, open(filepath, "wb") as out_file:
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                out_file.write(chunk)
    except Exception:
        os.remove(filepath)
        raise
    return Path(filepath)


def _local_audio_path(audio_url: str) -> Path:
    if _is_remote_url(audio_url):
        return _download_remote_audio(audio_url)
    return Path(audio_url)


class EssentiaAnalyzer:
    def __init__(self) -> None:
        if MonoLoader is None or RhythmExtractor2013 is None:
            raise ImportError(
                "Essentia is required for audio analysis. Install essentia and retry."
            )

    def analyze_song(self, song: Song) -> AudioAnalysis:
        if song.audio_url is None:
            raise ValueError("Song has no audio_url")

        local_path = _local_audio_path(song.audio_url)
        temporary_file = _is_remote_url(song.audio_url)

        try:
            audio = MonoLoader(filename=str(local_path))()
            extractor = RhythmExtractor2013(method="multifeature")
            bpm, beats, confidence, estimates, bpm_intervals = extractor(audio)
            return AudioAnalysis(
                bpm=float(bpm),
                confidence=float(confidence),
                beats=[float(value) for value in beats] if beats is not None else None,
                bpm_estimates=[
                    float(value) for value in estimates
                ]
                if estimates is not None
                else None,
                beat_intervals=[
                    float(value) for value in bpm_intervals
                ]
                if bpm_intervals is not None
                else None,
            )
        finally:
            if temporary_file and local_path.exists():
                local_path.unlink(missing_ok=True)