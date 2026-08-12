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
from typing import Optional, List, Any, Union
from PySide6.QtWidgets import QApplication

from workout.model import Interval, Workout
from workout.parser import parse_zwo_file
from workout.scheduler import WorkoutScheduler, WorkoutStatus
from music.player import MusicPlayer
from database.admin_client import create_admin_supabase
from recommendation.recommender import estimate_cadence_from_power
from ui.main_window import MainWindow
from database.workouts import list_workouts, get_workout_by_id

logger = logging.getLogger(__name__)


def _optional_float(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return float(value)


class AppController:
    def __init__(self):
        app = QApplication(sys.argv)
        self._app = app

        self.scheduler = WorkoutScheduler(self)
        self.music_player = MusicPlayer(self.scheduler)
        self.music_provider = self._discover_provider()
        self.admin_client = create_admin_supabase()

        window = MainWindow(self)
        window.show()
        sys.exit(app.exec())


    def get_current_song_name(self) -> str|None:
        return self.music_player.current_song_name()

    def is_music_available(self) -> bool:
        return self.music_player.available

    def get_audio_output(self):
        return self.music_player.audio_output

    def is_workout_available(self) -> bool:
        return False if self.scheduler is None else True

    def get_workout_state(self):
        return self.scheduler.get_state()

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
        state = self.get_scheduler_state()
        if state.status == WorkoutStatus.RUNNING:
            if state.interval_changed:
                self.music_player.next_track(True)
            self.music_player.play()
        elif state.status == WorkoutStatus.PAUSED or state.status == WorkoutStatus.NOT_STARTED:
            self.music_player.pause()
        else:
            self.music_player.stop()

    def _discover_provider(self):
        # keep previous behaviour but defensive: provider may be None
        try:
            return self.music_player.get_provider()
        except Exception:
            return None

    def load_and_prepare_workout(self, path: Path) -> None:
        """
        Load a workout file and create a WorkoutScheduler.
        Also triggers music provider precomputation if a provider can be discovered.
        Raises exceptions on invalid files (propagated to caller).
        """
        workout = self._load_workout_file(path)
        self.scheduler.initialize(workout)
        # notify provider to precompute recommendations
        if self.music_provider is not None:
            try:
                self.music_provider.precompute_recommendations(workout)
            except Exception:
                logger.exception("Music provider precompute failed")
        return

    def list_available_workouts(self) -> List[dict]:
        """
        Return a list of workouts available in the database.
        Each item is the raw row dict as returned by database.workouts.list_workouts.
        """
        return list_workouts(self.admin_client)

    def load_and_prepare_workout_from_db(self, record_or_id: Union[int, str, dict]) -> None:
        """
        Load workout from DB row (or id) and prepare scheduler.
        """
        if isinstance(record_or_id, (int, str)):
            row = get_workout_by_id(record_or_id, self.admin_client)
            if row is None:
                raise ValueError(f"No workout found with id {record_or_id}")
        elif isinstance(record_or_id, dict):
            row = record_or_id
        else:
            raise ValueError("Invalid workout identifier")

        intervals = row.get("intervals")
        if isinstance(intervals, str):
            try:
                intervals = json.loads(intervals)
            except json.JSONDecodeError:
                pass
        parsed = {
            "name": row.get("name"),
            "author": row.get("author"),
            "sport_type": row.get("sport_type") or row.get("sport_type_is_bike"),
            "tags": row.get("tags") or [],
            "description": row.get("description"),
            "intervals": intervals,
        }

        if isinstance(parsed, list):
            if not parsed:
                raise ValueError("Stored workout contains no workouts.")
            parsed = parsed[0]

        if not isinstance(parsed, dict):
            raise ValueError("Stored workout does not contain valid parsed data.")

        try:
            workout = Workout.from_parsed(parsed)
        except Exception:
            workout = self._build_workout_from_parsed_node(parsed)

        self.scheduler.initialize(workout)
        if self.music_provider is not None:
            try:
                self.music_provider.precompute_recommendations(workout)
            except Exception:
                logger.exception("Music provider precompute failed")
        return

    def _load_workout_file(self, path: Path) -> Workout:
        suffix = path.suffix.lower()
        if suffix == ".zwo":
            parsed = parse_zwo_file(path)
        elif suffix == ".json":
            with path.open("r", encoding="utf-8") as file:
                parsed = json.load(file)
        else:
            raise ValueError("Unsupported workout format. Please select a .json or .zwo file.")

        if isinstance(parsed, list):
            if not parsed:
                raise ValueError("Selected workout file contains no workouts.")
            parsed = parsed[0]

        if not isinstance(parsed, dict):
            raise ValueError("Workout file does not contain valid workout data.")

        try:
            return Workout.from_parsed(parsed)
        except ValueError:
            return self._build_workout_from_parsed_node(parsed)

    def _build_workout_from_parsed_node(self, parsed: dict) -> Workout:
        if not isinstance(parsed, dict):
            raise ValueError("Workout file does not contain valid workout data.")

        intervals = self._extract_intervals_from_node(parsed)
        if not intervals:
            raise ValueError(
                "Workout file does not contain interval data. "
                f"Parsed keys: {list(parsed.keys())}"
            )

        return Workout(
            name=parsed.get("name") or parsed.get("Name"),
            author=parsed.get("author") or parsed.get("Author"),
            sport_type=parsed.get("sport_type") or parsed.get("SportType"),
            tags=list(parsed.get("tags", [])),
            description=parsed.get("description") or parsed.get("Description"),
            intervals=intervals,
        )

    def _extract_intervals_from_node(self, node: dict) -> List[Interval]:
        if not isinstance(node, dict):
            return []

        if node.get("children"):
            intervals = []
            for child in node.get("children", []):
                intervals.extend(self._extract_intervals_from_node(child))
            return intervals

        if node.get("type") == "IntervalsT":
            return self._intervals_from_intervals_t(node.get("attrs", {}) or {})

        interval_info = node.get("interval") or {}
        duration = interval_info.get("duration")
        if duration is None:
            return []
        power = _optional_float(interval_info.get("power"))
        cadence = _optional_float(interval_info.get("cadence"))
        if cadence is None:
            cadence = estimate_cadence_from_power(power)

        return [
            Interval(
                duration=float(duration),
                power=power,
                cadence=cadence,
                type=node.get("type"),
                attrs=dict(node.get("attrs", {}) or {}),
            )
        ]

    def _intervals_from_intervals_t(self, attrs: dict) -> List[Interval]:
        repeat = int(attrs.get("Repeat") or 1)
        on_duration = attrs.get("OnDuration")
        off_duration = attrs.get("OffDuration")
        on_power = _optional_float(attrs.get("OnPower"))
        off_power = _optional_float(attrs.get("OffPower"))
        cadence = _optional_float(attrs.get("Cadence"))

        intervals: List[Interval] = []
        for _ in range(repeat):
            if on_duration is not None:
                intervals.append(
                    Interval(
                        duration=float(on_duration),
                        power=on_power,
                        cadence=cadence,
                        type="IntervalsT",
                        attrs=dict(attrs),
                    )
                )
            if off_duration is not None:
                intervals.append(
                    Interval(
                        duration=float(off_duration),
                        power=off_power,
                        cadence=cadence,
                        type="IntervalsT",
                        attrs=dict(attrs),
                    )
                )
        return intervals