from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, List, Any

from workout.scheduler import WorkoutScheduler
from database.client import supabase
from database.songs import get_playable_songs
from music.model import Song
from recommendation.recommender import recommend, Recommendation  # new dependency

AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
RECOMMENDER_CANDIDATE_POOL = 100
RECOMMENDER_LIMIT_PER_INTERVAL = 10


class SongProvider:
    def __init__(self, scheduler=WorkoutScheduler, client=None) -> None:
        self._client = client or supabase
        self._songs: List[Song] = []
        self._current_index = -1
        self._interval_recs = {}  # type: dict[int, list]
        self.scheduler: WorkoutScheduler = scheduler
        self._load_songs()

    def _load_songs(self) -> None:
        try:
            songs = get_playable_songs(client=self._client)
        except Exception:
            songs = []
            print("Unable to get songs from the database")
        self._songs = songs

    def has_songs(self) -> bool:
        return bool(self._songs)

    def get_current_song(self) -> Optional[Song]:
        interval_index = self.scheduler.current_interval_index()
        return self.choose_song_for_interval(interval_index)

    def next_song(self, interval_changed: bool = False) -> Optional[Song]:
        if interval_changed:
            self._current_index = 0
        else:
            self._current_index += 1
        interval_index = self.scheduler.current_interval_index()
        song = self.choose_song_for_interval(interval_index)
        return song

    def precompute_recommendations(self, workout: Any) -> None:
        """
        Precompute recommendations for each interval in the workout.
        Stores results in self._interval_recs keyed by interval index.
        Safe to call multiple times; will overwrite previous cache for this provider instance.
        """
        try:
            intervals = getattr(workout, "intervals", None) or getattr(workout, "steps", None) or []
            if not intervals:
                self._interval_recs = {}
                return
            candidates = self._songs[:RECOMMENDER_CANDIDATE_POOL]
            self._interval_recs = {}
            for idx, interval in enumerate(intervals):
                recs = recommend(interval, candidates, limit=RECOMMENDER_LIMIT_PER_INTERVAL)
                self._interval_recs[idx] = recs
        except Exception:
            # never crash the host when precomputing; log and continue
            import logging
            logging.getLogger(__name__).exception("precompute_recommendations failed")

    def get_recommendations_for_interval(self, interval_index: int, fallback_repository: Optional[Any] = None, limit: Optional[int] = None) -> list:
        """
        Return precomputed recommendations for an interval index.
        If not precomputed, compute on-demand using fallback_repository or internal pool.
        """
        try:
            recs = self._interval_recs[interval_index]
            return recs[:limit] if limit is not None else recs
        except Exception:
            return []

    def choose_song_for_interval(self, interval_index: int) -> Optional[Any]:
        """
        Return the top recommended song for an interval.
        """
        recs = self.get_recommendations_for_interval(interval_index)
        if recs:
            print(f"Song index: {self._current_index}")
            song = recs[self._current_index].song
            print(f"Song: {song.title}, BPM: {song.bpm}, Genre: {song.genre}")
            return recs[self._current_index].song
        else:
            return self._songs[interval_index * 5 + self._current_index]