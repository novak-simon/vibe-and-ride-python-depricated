from __future__ import annotations

import logging
import os
import shutil
import tempfile
import urllib.request
from contextlib import contextmanager
from typing import Iterator, Optional

from database.songs import fetch_unanalyzed_songs, update_song_analysis
from analysis.librosa_analyzer import LibrosaAnalyzer
from music.model import Song

logger = logging.getLogger(__name__)


class AudioAnalysisService:
    def __init__(self, db_client, analyzer: Optional[LibrosaAnalyzer] = None) -> None:
        self.db_client = db_client
        self.analyzer = analyzer or LibrosaAnalyzer()

    def analyze_batch(self, limit: int = 50) -> None:
        songs = fetch_unanalyzed_songs(self.db_client, limit=limit)
        if not songs:
            print("No songs found for analysis.")
            return

        for index, song in enumerate(songs, start=1):
            print(f"Analyzing {index}/{len(songs)}: {song.title}")
            try:
                with self._prepare_local_audio(song) as audio_path:
                    analysis = self.analyzer.analyze(audio_path)

                update_song_analysis(self.db_client, song.id, analysis)

                print(f"  BPM: {analysis.bpm:.2f}")
                print(
                    f"  Confidence: "
                    f"{analysis.bpm_confidence if analysis.bpm_confidence is not None else 'None'}"
                )
                print(f"  Beats: {len(analysis.beats)}")
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