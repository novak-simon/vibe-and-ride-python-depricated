from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, List, Any

from database.client import supabase
from database.songs import get_playable_songs
from music.model import Song
from recommendation.recommender import recommend  # new dependency

AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
RECOMMENDER_CANDIDATE_POOL = 50
RECOMMENDER_LIMIT_PER_INTERVAL = 10


class SongProvider:
    def __init__(self, client=None) -> None:
        self._client = client or supabase
        self._songs: List[Song] = []
        self._current_index = -1
        self._interval_recs = {}  # type: dict[int, list]
        self._load_songs()

    def _load_songs(self) -> None:
        try:
            songs = get_playable_songs(client=self._client)
        except Exception:
            songs = []
            print("Unable to get songs from the database")

        self._songs = songs
        self._current_index = 0 if self._songs else -1

    def has_songs(self) -> bool:
        return bool(self._songs)

    def get_current_song(self) -> Optional[Song]:
        if self._current_index < 0 or self._current_index >= len(self._songs):
            return None
        return self._songs[self._current_index]

    def next_song(self) -> Optional[Song]:
        if not self._songs:
            return None
        self._current_index = (self._current_index + 1) % len(self._songs)
        return self.get_current_song()

    def songs(self) -> List[Song]:
        return list(self._songs)

    def fetch_candidate_songs(self, repository: Optional[Any] = None) -> list:
        """
        Return a list of candidate song objects for the recommender.
        Prefer caller-supplied repository or internal song pool if available.
        The recommender will receive up to RECOMMENDER_CANDIDATE_POOL items.
        """
        # try common locations without forcing any architecture change
        songs = []
        if repository is not None:
            try:
                songs = list(repository.list_songs() if hasattr(repository, "list_songs") else repository.get_all())
            except Exception:
                try:
                    songs = list(repository)
                except Exception:
                    songs = []
        else:
            # fallbacks: attributes that projects commonly expose
            songs_attr = getattr(self, "songs", None) or getattr(self, "song_pool", None) or getattr(self, "_songs", None)
            if isinstance(songs_attr, Iterable):
                songs = list(songs_attr)
        # deterministic ordering: do not randomize here
        return songs[:RECOMMENDER_CANDIDATE_POOL]

    def precompute_recommendations(self, workout: Any, repository: Optional[Any] = None):
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
            candidates = self.fetch_candidate_songs(repository=repository)
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
        if interval_index in self._interval_recs:
            recs = self._interval_recs[interval_index]
            return recs[:limit] if limit is not None else recs
        # on-demand compute
        try:
            # attempt to find workout intervals context to build interval object - conservative approach:
            candidates = self.fetch_candidate_songs(repository=fallback_repository)
            # We don't have the interval instance here; caller should pass it if on-demand is required.
            return []
        except Exception:
            return []

    def choose_song_for_interval(self, interval_index: int, interval_obj: Any, repository: Optional[Any] = None) -> Optional[Any]:
        """
        Return the top recommended song for an interval.
        Tries precomputed recommendations first; if none, computes recommendations on-demand.
        """
        recs = self.get_recommendations_for_interval(interval_index)
        if recs:
            return recs[0].song
        # compute on-demand
        candidates = self.fetch_candidate_songs(repository=repository)
        recs = recommend(interval_obj, candidates, limit=1)
        return recs[0].song if recs else None