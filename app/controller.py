"""
Application controller: separates workout/music logic from UI.

Responsibilities:
- Load and parse workout files
- Build Workout objects from parsed content
- Create WorkoutScheduler and notify music provider to precompute recommendations
"""
from __future__ import annotations
import sys
from pathlib import Path
import json
import logging
from typing import Optional, List, Any, Union, Dict
from PySide6.QtWidgets import QApplication

from workout.model import Interval, Workout
from workout.scheduler import WorkoutScheduler, WorkoutStatus
from music.player import MusicPlayer
from database.admin_client import create_admin_supabase
from ui.main_window import MainWindow
from database.workouts import list_workouts, get_workout_by_id
from database.user_song_stats import increment_skip_count
from recommendation.recommender import set_recommendation_debug_sink

logger = logging.getLogger(__name__)



class AppController:
    def __init__(self):
        app = QApplication(sys.argv)
        self._app = app

        self.scheduler = WorkoutScheduler(self)
        self.music_player = MusicPlayer(self.scheduler)
        self.admin_client = create_admin_supabase()
        self._last_recommendation_debug: Optional[Dict[str, Any]] = None

        # register recommendation debug sink
        set_recommendation_debug_sink(self._on_recommendation_debug)

        window = MainWindow(self)
        window.show()
        sys.exit(app.exec())

    def get_workout_scheduler(self) -> WorkoutScheduler:
        return self.scheduler
    
    def get_music_player(self) -> MusicPlayer:
        return self.music_player

    def get_current_song_title(self) -> str|None:
        return self.music_player.current_song().title if self.music_player.current_song() is not None else None

    def is_music_available(self) -> bool:
        return self.music_player.available

    def get_audio_output(self):
        return self.music_player.audio_output

    def is_workout_available(self) -> bool:
        return False if self.scheduler is None else True

    def get_workout_state(self):
        return self.scheduler.get_state()
    def list_available_workouts(self) -> List[dict]:
        return list_workouts(self.admin_client)

    def get_workout(self):
        return self.scheduler.workout
    
    def start_workout(self) -> None:
            self.scheduler.start()

    def pause(self):
        self.scheduler.pause()

    def resume(self):
        self.scheduler.resume()

    def reset(self):
        self.scheduler.reset()

    def resync(self, time):
        self.scheduler.resync(time)

    def refresh_state(self):
        state = self.get_workout_state()
        if state.status == WorkoutStatus.RUNNING:
            if state.interval_changed:
                print('Tady bych snad mel byt')
                self.music_player.next_track(True)
            self.music_player.play()
        elif state.status == WorkoutStatus.PAUSED or state.status == WorkoutStatus.NOT_STARTED:
            self.music_player.pause()
        else:
            self.music_player.stop()

    def load_and_prepare_workout(self, path: Path = None, workout_id: str = None) -> None:
        """
        Initializes scheduler with valid path or workout_id.
        """
        if not workout_id is None:
            self.scheduler.initialize(workout_id=workout_id)
        elif not path is None:
            self.scheduler.initialize(path=path)
        else:
            raise ValueError("Couldn't load and prepare workout: Invalid path or workout id")

    def list_available_workouts(self):
        return list_workouts(self.admin_client)

    def _on_recommendation_debug(self, payload: Dict[str, Any]) -> None:
        self._last_recommendation_debug = payload

    def get_current_interval_debug_info(self) -> Optional[Dict[str, Any]]:
        """
        Returns debug info for current interval from latest recommender payload.
        Supports current payload shape: {"intervals": [...]}.
        """
        payload = self._last_recommendation_debug
        if not payload:
            return None

        state = self.get_workout_state()
        idx = state.interval_index
        if idx is None:
            return None

        # New recommender payload key
        interval_items = payload.get("intervals") or []
        if not isinstance(interval_items, list):
            return None
        if idx < 0 or idx >= len(interval_items):
            return None
        return interval_items[idx]

    def skip(self) -> None:
        increment_skip_count(song_id=self.music_player.current_song().id, user_id=None, client=self.admin_client)
        self.music_player.next_track()