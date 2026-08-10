from __future__ import annotations

import logging
import os
import shutil
import tempfile
import urllib.request
from contextlib import contextmanager
from typing import Iterator, Optional, List
import numpy as np
import math

from database.songs import fetch_unanalyzed_songs, update_song_analysis, get_song_by_id, fetch_songs
from analysis.librosa_analyzer import LibrosaAnalyzer
from analysis.beatnet_analyzer import BeatnetAnalyzer
from analysis.model import AudioAnalysis
from music.model import Song

logger = logging.getLogger(__name__)


class AudioAnalysisService:
    def __init__(self, db_client) -> None:
        self.db_client = db_client
        self.analyzer = LibrosaAnalyzer()
        self.alternative_analyzer = BeatnetAnalyzer()

    def analyze_batch(self, limit: int = 50, force: bool = False) -> None:
        if force:
            songs = fetch_songs(self.db_client, limit=limit)
        else:
            songs = fetch_unanalyzed_songs(self.db_client, limit=limit)
        if not songs:
            print("No songs found for analysis.")
            return

        for index, song in enumerate(songs, start=1):
            print(f"Analyzing {index}/{len(songs)}: {song.title}")
            self.analyze_song(song)

    def analyze_by_id(self, id: int) -> None:
        song = get_song_by_id(id, self.db_client)
        print(f"Analyzing {song.title}")
        self.analyze_song(song)


    def analyze_song(self, song: Song) -> None:
        try:
            with self._prepare_local_audio(song) as audio_path:
                analysis = self.analyzer.analyze(audio_path)
                alternative_analysis = self.alternative_analyzer.analyze(audio_path)
                final_analysis: AudioAnalysis = self._merge_analysis(analysis, alternative_analysis)

            update_song_analysis(self.db_client, song.id, final_analysis)

            print(f"  BPM: {final_analysis.bpm}")
            print(
                f"  Confidence: "
                f"{final_analysis.bpm_confidence if final_analysis.bpm_confidence is not None else 'None'}"
            )
        except Exception as err:
            logger.exception("Failed to analyze song %s (%s)", song.title, song.id)
            print(f"  FAILED: {err}")


    @contextmanager
    def _prepare_local_audio(self, song: Song) -> Iterator[str]:
        if song.id is None:
            raise ValueError("Song has no database id")

        source_url = song.download_url or song.audio_url
        if not source_url:
            raise ValueError("Song has no audio_url or download_url")

        if source_url.startswith("file://"):
            local_path = source_url[7:]
            cleanup = False
        elif os.path.exists(source_url):
            local_path = source_url
            cleanup = False
        else:
            local_path = self._download_remote_audio(source_url)
            cleanup = True

        try:
            yield local_path
        finally:
            if cleanup and os.path.exists(local_path):
                try:
                    os.remove(local_path)
                except OSError:
                    logger.warning("Unable to remove temporary audio file %s", local_path)

    def _download_remote_audio(self, url: str) -> str:
        suffix = os.path.splitext(url.split("?", 1)[0])[1] or ".mp3"
        fd, local_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)

        request = urllib.request.Request(
            url, headers={"User-Agent": "zwift-music/librosa-analyzer"}
        )
        with urllib.request.urlopen(request, timeout=60) as remote_stream, open(
            local_path, "wb"
        ) as local_file:
            shutil.copyfileobj(remote_stream, local_file)

        return local_path

    def _merge_analysis(self, analysis1: AudioAnalysis, analysis2: AudioAnalysis) -> AudioAnalysis:
        relation = analysis2.bpm / analysis1.bpm
        tolerance = 0.15
        if 2-tolerance < relation and relation < 2+tolerance:
            relation_estimate = 2
        elif 3-tolerance < relation and relation < 3+tolerance:
            relation_estimate = 3
        elif 4-tolerance < relation and relation < 4+tolerance:
            relation_estimate = 4
        elif 1/2 - tolerance < relation and relation < 1/2 + tolerance:
            relation_estimate = 0.5
        elif 1/3-tolerance < relation and relation < 1/3+tolerance:
            relation_estimate = 1/3
        elif 1/4-tolerance < relation and relation < 1/4+tolerance:
            relation_estimate = 1/4
        else:
            relation_estimate = 1
        analysis2bpm = analysis2.bpm / relation_estimate
        if relation_estimate > 1:
            k = int(relation_estimate)
            analysis2intervals = analysis2.beat_intervals[::k]
            analysis1intervals = analysis1.beat_intervals
        else:
            k = int(1 / relation_estimate)
            analysis2intervals = analysis2.beat_intervals
            analysis1intervals = analysis1.beat_intervals[::k]
        final_bpm = round((analysis1.bpm * analysis1.bpm_confidence + analysis2bpm  * analysis2.bpm_confidence) / (analysis1.bpm_confidence + analysis2.bpm_confidence))
        final_confidence = round((analysis1.bpm_confidence if analysis2.bpm_confidence == 0 else ((analysis1.bpm_confidence + analysis2.bpm_confidence) / 2)) - 3 * math.sqrt(abs(analysis1.bpm - analysis2bpm)))
        final_intervals = []
        for i in range(max(len(analysis1intervals), len(analysis2intervals))):
            if i < len(analysis1intervals):
                interval1 = analysis1intervals[i]
            else:
                interval1 = None
            if i < len(analysis2intervals):
                interval2 = analysis2intervals[i]
            else:
                interval2 = None
            if interval2 is None:
                final_intervals.append(interval1)
                continue
            elif interval1 is None:
                final_intervals.append(interval2)
                continue
            final_intervals.append(interval1 + interval2 / 2)
        final_analysis: AudioAnalysis = AudioAnalysis(
        bpm= final_bpm,
        bpm_confidence= final_confidence,
        beat_intervals= final_intervals,
        )
        return final_analysis