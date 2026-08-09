from __future__ import annotations

import logging
from typing import Any, List, Optional, Tuple

from analysis.essentia import EssentiaAnalyzer
from analysis.model import AudioAnalysis
from database.songs import get_songs_needing_analysis, update_song_analysis
from music.model import Song

logger = logging.getLogger(__name__)


def analyze_song(
    song: Song,
    analyzer: Optional[EssentiaAnalyzer] = None,
    client: Any | None = None,
) -> Tuple[Optional[AudioAnalysis], Optional[str]]:
    analyzer = analyzer or EssentiaAnalyzer()
    try:
        analysis = analyzer.analyze_song(song)
        update_song_analysis(
            song_id=song.id,
            jamendo_id=song.jamendo_id,
            bpm=analysis.bpm,
            bpm_confidence=analysis.confidence,
            beats=analysis.beats,
            bpm_estimates=analysis.bpm_estimates,
            beat_intervals=analysis.beat_intervals,
            client=client,
        )
        return analysis, None
    except Exception as exc:
        logger.exception("Failed to analyze song %s", song.jamendo_id)
        return None, str(exc)


def analyze_songs(
    limit: int = 50,
    client: Any | None = None,
    analyzer: Optional[EssentiaAnalyzer] = None,
) -> List[Tuple[Song, Optional[AudioAnalysis], Optional[str]]]:
    analyzer = analyzer or EssentiaAnalyzer()
    songs = get_songs_needing_analysis(client=client, limit=limit)
    results: List[Tuple[Song, Optional[AudioAnalysis], Optional[str]]] = []
    for index, song in enumerate(songs, start=1):
        logger.info("Analyzing %d/%d: %s", index, len(songs), song.title)
        analysis, error = analyze_song(song, analyzer=analyzer, client=client)
        results.append((song, analysis, error))
    return results