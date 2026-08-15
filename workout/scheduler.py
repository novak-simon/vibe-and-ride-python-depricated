from __future__ import annotations
from pathlib import Path
import json

import time
from dataclasses import dataclass
from typing import Callable, Optional, Any, List
import logging
logger = logging.getLogger(__name__)

from .model import Interval, Workout
from workout.parser import parse_zwo_file
from database.workouts import get_workout_by_id
from database.admin_client import create_admin_supabase
from helper_methods.model_methods import estimate_cadence_from_power


_UNSET_LAST_INTERVAL = object()


class WorkoutSchedulerError(Exception):
    pass


class WorkoutStatus(str):
    NOT_STARTED = "not_started"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"


@dataclass(frozen=True)
class WorkoutState:
    status: str
    interval_index: Optional[int]
    current_interval: Optional[Interval]
    elapsed_in_interval: float
    remaining_in_interval: float
    interval_length: float
    total_elapsed: float
    total_remaining: float
    interval_changed: bool


class WorkoutScheduler:
    def __init__(self, controller: Any, time_fn: Optional[Callable[[], float]] = None):
        self.controller = controller
        self.music_player = None
        self.workout = None
        self._time_fn = time_fn or time.monotonic
        self._status = WorkoutStatus.NOT_STARTED
        self._start_monotonic: Optional[float] = None
        self._elapsed_before_start = 0.0
        self._last_interval_index = _UNSET_LAST_INTERVAL
        self.admin_client = create_admin_supabase()


    @property
    def status(self) -> str:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._status == WorkoutStatus.RUNNING

    @property
    def is_paused(self) -> bool:
        return self._status == WorkoutStatus.PAUSED

    @property
    def is_finished(self) -> bool:
        return self._status == WorkoutStatus.FINISHED

    def initialize(self, path: Path = None, workout_id = None) -> None:
        self.music_player = self.controller.get_music_player()
        if not workout_id is None:
            row = get_workout_by_id(workout_id, self.admin_client)
            workout = self.db_row_to_workout(row)
        elif not path is None:
            workout = self._load_workout_file(path)
        else:
            return
        if workout is None:
            raise ValueError("Workout cannot be None")
        self.workout = workout
        print(f"Workout initialized: {self.workout.name if self.workout else 'None'}")
        self.music_player.workout_chosen(self.workout)


    def start(self) -> None:
        if self.is_running:
            return
        if self.workout.total_duration <= 0:
            self._status = WorkoutStatus.FINISHED
            self._elapsed_before_start = 0.0
            self._start_monotonic = None
            self._last_interval_index = _UNSET_LAST_INTERVAL
            return
        self._status = WorkoutStatus.RUNNING
        self._elapsed_before_start = 0.0
        self._start_monotonic = self._time_fn()
        self._last_interval_index = _UNSET_LAST_INTERVAL

    def pause(self) -> None:
        if not self.is_running:
            raise WorkoutSchedulerError("Cannot pause when workout is not running")
        self._elapsed_before_start = self._current_elapsed()
        self._start_monotonic = None
        self._status = WorkoutStatus.PAUSED

    def resume(self) -> None:
        if not self.is_paused:
            raise WorkoutSchedulerError("Cannot resume when workout is not paused")
        self._start_monotonic = self._time_fn()
        self._status = WorkoutStatus.RUNNING

    def reset(self) -> None:
        self._status = WorkoutStatus.NOT_STARTED
        self._start_monotonic = None
        self._elapsed_before_start = 0.0
        self._last_interval_index = _UNSET_LAST_INTERVAL

    def resync(self, workout_time: float) -> None:
        if workout_time < 0:
            raise ValueError("Workout time for resync must be non-negative")
        clamped_time = min(workout_time, self.workout.total_duration)
        running = self.is_running
        self._elapsed_before_start = clamped_time
        if running:
            self._start_monotonic = self._time_fn()
            if clamped_time >= self.workout.total_duration:
                self._status = WorkoutStatus.FINISHED
                self._start_monotonic = None
        else:
            self._start_monotonic = None
            if clamped_time >= self.workout.total_duration:
                self._status = WorkoutStatus.FINISHED
            elif self._status == WorkoutStatus.NOT_STARTED and clamped_time == 0.0:
                self._status = WorkoutStatus.NOT_STARTED
            else:
                self._status = WorkoutStatus.PAUSED
        self._last_interval_index = _UNSET_LAST_INTERVAL

    def get_state(self) -> WorkoutState:
        total_elapsed = self._current_elapsed()
        if self.is_running and total_elapsed >= self.workout.total_duration:
            self._status = WorkoutStatus.FINISHED
            self._start_monotonic = None
            self._elapsed_before_start = self.workout.total_duration
            total_elapsed = self.workout.total_duration

        interval_index, interval, interval_start = self._find_interval(total_elapsed)
        if interval is None:
            elapsed_in_interval = 0.0
            remaining_in_interval = 0.0
            interval_length = 0.0
        else:
            elapsed_in_interval = total_elapsed - interval_start
            remaining_in_interval = max(0.0, interval.duration - elapsed_in_interval)
            interval_length = interval.duration

        interval_changed = (
            self._last_interval_index is _UNSET_LAST_INTERVAL
            or interval_index != self._last_interval_index
        )
        self._last_interval_index = interval_index

        return WorkoutState(
            status=self._status,
            interval_index=interval_index,
            current_interval=interval,
            elapsed_in_interval=elapsed_in_interval,
            remaining_in_interval=remaining_in_interval,
            interval_length=interval_length,
            total_elapsed=total_elapsed,
            total_remaining=max(0.0, self.workout.total_duration - total_elapsed) if not self.workout is None else 0.0,
            interval_changed=interval_changed,
        )

    def current_interval_index(self) -> Optional[int]:
        return self.get_state().interval_index

    def current_interval(self) -> Optional[Interval]:
        return self.get_state().current_interval

    def _current_elapsed(self) -> float:
        if self.is_running and self._start_monotonic is not None:
            return min(
                self._elapsed_before_start + (self._time_fn() - self._start_monotonic),
                self.workout.total_duration,
            )
        elif not self.workout is None:
            return min(self._elapsed_before_start, self.workout.total_duration)
        else:
            return self._elapsed_before_start

    def _find_interval(self, workout_time: float):
        elapsed = 0.0
        if not self.workout is None:
            for index, interval in enumerate(self.workout.intervals):
                if workout_time < elapsed + interval.duration:
                    return index, interval, elapsed
                elapsed += interval.duration
        return None, None, elapsed

    
    def _optional_float(value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        return float(value)


    # Attempt to notify music provider to start precomputing whenever a workout is chosen.
    # This integration is intentionally small and defensive: it only calls provider if the scheduler
    # has a reference to one (common in applications where components are wired together).
    

    def _notify_provider_workout_chosen(self, workout):
        """
        Should be invoked right after the scheduler selects/accepts a workout.
        """
        try:
            if self.provider is None:
                return
            # If the provider supports precompute_recommendations, call it.
            precompute = getattr(self.provider, "precompute_recommendations", None)
            if callable(precompute):
                # Attempt to pass provider's known repository if available to avoid extra DB work.
                repo = getattr(self.provider, "song_repository", None)
                precompute(workout, repository=repo)
        except Exception:
            logger.exception("Failed to notify music provider about selected workout")

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
        power = self._optional_float(interval_info.get("power"))
        cadence = self._optional_float(interval_info.get("cadence"))
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
        on_power = self._optional_float(attrs.get("OnPower"))
        off_power = self._optional_float(attrs.get("OffPower"))
        cadence = self._optional_float(attrs.get("Cadence"))

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

    def db_row_to_workout(self, row: int|str|dict) -> Workout:
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
        return workout