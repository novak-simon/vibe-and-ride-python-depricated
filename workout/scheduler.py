from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional
import logging
logger = logging.getLogger(__name__)

from .model import Interval, Workout

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
    total_elapsed: float
    total_remaining: float
    interval_changed: bool


class WorkoutScheduler:
    def __init__(self, workout: Workout, time_fn: Optional[Callable[[], float]] = None):
        if workout is None:
            raise ValueError("Workout cannot be None")
        self.workout = workout
        self._time_fn = time_fn or time.monotonic
        self._status = WorkoutStatus.NOT_STARTED
        self._start_monotonic: Optional[float] = None
        self._elapsed_before_start = 0.0
        self._last_interval_index = _UNSET_LAST_INTERVAL
        self._notify_provider_workout_chosen(self.workout)

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
        else:
            elapsed_in_interval = total_elapsed - interval_start
            remaining_in_interval = max(0.0, interval.duration - elapsed_in_interval)

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
            total_elapsed=total_elapsed,
            total_remaining=max(0.0, self.workout.total_duration - total_elapsed),
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
        return min(self._elapsed_before_start, self.workout.total_duration)

    def _find_interval(self, workout_time: float):
        elapsed = 0.0
        for index, interval in enumerate(self.workout.intervals):
            if workout_time < elapsed + interval.duration:
                return index, interval, elapsed
            elapsed += interval.duration
        return None, None, elapsed

    # Attempt to notify music provider to start precomputing whenever a workout is chosen.
    # This integration is intentionally small and defensive: it only calls provider if the scheduler
    # has a reference to one (common in applications where components are wired together).
    

    def _notify_provider_workout_chosen(self, workout):
        """
        Defensive helper: call precompute_recommendations on an attached music provider if present.
        Should be invoked right after the scheduler selects/accepts a workout.
        """
        try:
            provider = getattr(self, "music_provider", None) or getattr(self, "provider", None)
            if provider is None:
                return
            # If the provider supports precompute_recommendations, call it.
            precompute = getattr(provider, "precompute_recommendations", None)
            if callable(precompute):
                # Attempt to pass provider's known repository if available to avoid extra DB work.
                repo = getattr(provider, "song_repository", None)
                precompute(workout, repository=repo)
        except Exception:
            logger.exception("Failed to notify music provider about selected workout")