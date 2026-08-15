from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional, List, Any

from workout.model import Workout
from workout.scheduler import WorkoutScheduler
from database.client import supabase
from database.songs import get_playable_songs
from music.model import Song
from recommendation.recommender import recommend, SongRecommendation  # new dependency

AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}


class SongProvider:
    def __init__(self, scheduler=WorkoutScheduler, client=None) -> None:
        self._client = client or supabase
        self._songs: List[Song] = []
        self._current_index = -1
        self._interval_recs = []
        self.recommendation_debug_info: Optional[List[SongRecommendation]] = None  # Store the last recommendation debug information
        self.scheduler: WorkoutScheduler = scheduler
        self._load_songs()

    def has_songs(self) -> bool:
        return bool(self._songs)

    def has_recommendations(self) -> bool:
        if self.scheduler is None:
            return False
        elif len(self._interval_recs) >= (self.scheduler.current_interval_index() + 1) + 1:
            return True
        elif self.scheduler.current_interval_index() + 1 >= len(self.scheduler.workout.intervals):
            return True  # No next interval, so no recommendations needed
        return False

    def get_current_song(self) -> Optional[Song]:
        interval_index = self.scheduler.current_interval_index()
        if self.scheduler.workout is None:
            return Song("None")
        return self.choose_song_for_interval(interval_index)

    def next_song(self, interval_changed: bool = False) -> Optional[Song]:
        print("Next Song")
        if interval_changed:
            print("Interval changed")
            self._current_index = 0
        else:
            self._current_index += 1
        interval_index = self.scheduler.current_interval_index()
        song = self.choose_song_for_interval(interval_index)
        return song

    def precompute_recommendations(self, workout: Workout, interval_index: int) -> None:
        """
        Precompute recommendations for each interval in the workout.
        Stores results in self._interval_recs keyed by interval index.
        Safe to call multiple times; will overwrite previous cache for this provider instance.
        """
        
        try:
            if not workout:
                self._interval_recs = []
                return
            elif interval_index >= len(workout.intervals):
                return  # Invalid interval index; do nothing
            if not self._interval_recs or len(self._interval_recs) <= interval_index:
                self._interval_recs.append(None)  # Ensure the list is long enough
            interval = workout.intervals[interval_index]
            print(f"Precomputing recommendations for interval {interval_index} of workout {workout.name if workout else 'None'}")
            self._interval_recs[interval_index], self.recommendation_debug_info = recommend(interval)
            print(f"Recommendation debug info for interval {interval_index}: {len(self.recommendation_debug_info)}")
            print(f"Precomputed {len(self._interval_recs[interval_index])} recommendations for interval {interval_index}")
        except Exception:
            # never crash the host when precomputing; log and continue
            import logging
            logging.getLogger(__name__).exception("precompute_recommendations failed")

    def choose_song_for_interval(self, interval_index: int) -> Optional[Any]:
        """
        Return the top recommended song for an interval.
        """
        if self._interval_recs:
            recs = self._interval_recs[interval_index]
        else:
            recs = []
        if recs:
            print(f"Choosing song for interval {interval_index}: {len(recs)} recommendations available, current index: {self._current_index}")
            return recs[self._current_index]
        else:
            return self._songs[interval_index * 5 + self._current_index]

    def _load_songs(self) -> None:
            try:
                songs = get_playable_songs(client=self._client)
            except Exception:
                songs = []
                print("Unable to get songs from the database")
            self._songs = songs