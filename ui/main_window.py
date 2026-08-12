from __future__ import annotations
import logging
import json

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from workout.model import Interval, Workout
from workout.parser import parse_zwo_file
from workout.scheduler import WorkoutScheduler, WorkoutStatus

from .formatting import format_seconds

logger = logging.getLogger(__name__)

def _optional_float(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return float(value)


class MainWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.setWindowTitle("Zwift Music")
        # controller mediates logic (file parsing, scheduler creation, provider precompute)
        self._controller = controller
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_state)
        self._timer.start(200)

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)

        self._load_button = QPushButton("Select workout...")
        self._load_button.clicked.connect(self._load_workout)

        self._workout_name_label = QLabel("No workout loaded")
        self._workout_name_label.setAlignment(Qt.AlignLeft)

        self._interval_count_label = QLabel("")
        self._interval_count_label.setAlignment(Qt.AlignLeft)

        self._interval_label = QLabel("Interval: -")
        self._interval_label.setAlignment(Qt.AlignLeft)

        self._interval_detail_label = QLabel("Current interval details will appear here.")
        self._interval_detail_label.setWordWrap(True)

        self._song_label = QLabel(
            f"Song: {self._controller.get_current_song_name() or 'none'}"
        )
        self._song_label.setWordWrap(True)
        self._music_status_label = QLabel(
            f"Music: {'enabled' if self._controller.is_music_available() else 'disabled'}"
        )
        self._interval_time_label = QLabel("Interval time: 00:00 / 00:00")
        self._workout_time_label = QLabel("Workout time: 00:00 / 00:00")
        self._status_label = QLabel("Status: no workout loaded")

        self._start_button = QPushButton("Start")
        self._start_button.clicked.connect(self._start_workout)

        self._pause_button = QPushButton("Pause")
        self._pause_button.clicked.connect(self._toggle_pause_resume)

        self._reset_button = QPushButton("Reset")
        self._reset_button.clicked.connect(self._reset_workout)

        self._resync_button = QPushButton("Resynchronize")
        self._resync_button.clicked.connect(self._resync_workout)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self._start_button)
        button_layout.addWidget(self._pause_button)
        button_layout.addWidget(self._reset_button)
        button_layout.addWidget(self._resync_button)

        layout = QVBoxLayout()
        layout.addWidget(self._load_button)
        layout.addWidget(self._workout_name_label)
        layout.addWidget(self._interval_count_label)
        layout.addWidget(self._interval_label)
        layout.addWidget(self._interval_detail_label)
        layout.addWidget(self._song_label)
        layout.addWidget(self._music_status_label)
        layout.addWidget(self._interval_time_label)
        layout.addWidget(self._workout_time_label)
        layout.addLayout(button_layout)
        layout.addWidget(self._status_label)
        layout.addStretch(1)

        central.setLayout(layout)
        self._update_controls()

    def _load_workout(self) -> None:
        """
        - Show a simple chooser with workouts from DB (default).
        - Provide "Import my own workout..." option which falls back to file picker and existing import flow.
        """
        try:
            rows = self._controller.list_available_workouts()
        except Exception as exc:
            logger.exception("Failed to list workouts from DB")
            rows = []

        choices = []
        id_map = []
        # Default top choice: import your own
        choices.append("Import my own workout...")
        id_map.append(None)

        for row in rows:
            name = row.get("name") or "<unnamed>"
            author = row.get("author")
            display = f"{name}" + (f" — {author}" if author else "")
            choices.append(display)
            id_map.append(row.get("id"))

        # If there are no DB workouts, inform user but still allow import via that first choice.
        item, ok = QInputDialog.getItem(
            self,
            "Select workout",
            "Choose a workout (library is default):",
            choices,
            0,
            False,
        )
        if not ok:
            return

        selected_index = choices.index(item)
        selected_id = id_map[selected_index]

        if selected_id is None:
            # Import flow (existing)
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Select workout file",
                "",
                "Workout files (*.zwo);;Zwift workout files (*.zwo)",
            )
            if not path:
                return
            try:
                # delegate parsing/creation to controller
                self._controller.load_and_prepare_workout(path=Path(path))
            except Exception as exc:
                QMessageBox.critical(self, "Workout load failed", str(exc))
                return
        else:
            # Load from DB
            try:
                self._controller.load_and_prepare_workout(workout_id=selected_id)
            except Exception as exc:
                QMessageBox.critical(self, "Workout load failed", str(exc))
                return

        workout = self._controller.get_workout()
        self._workout_name_label.setText(f"Workout: {workout.name or 'Unnamed'}")
        self._interval_count_label.setText(f"{len(workout.intervals)} intervals")
        self._refresh_state()
        self._update_controls()

    def _start_workout(self) -> None:
        if not self._controller.is_workout_available():
            QMessageBox.warning(self, "No workout", "Please load a workout before starting.")
            return

        # keep UI responsibilities only; start scheduling via scheduler object
        self._controller.start_workout()
        self._timer.start(200)
        self._refresh_state()
        self._update_controls()

    def _toggle_pause_resume(self) -> None:
        if not self._controller.is_workout_available():
            return

        if self._controller.get_workout_state().status is WorkoutStatus.RUNNING:
            try:
                self._controller.pause()
            except Exception as exc:
                QMessageBox.warning(self, "Pause failed", str(exc))
        elif self._controller.get_workout_state().status is WorkoutStatus.PAUSED:
            try:
                self._controller.resume()
            except Exception as exc:
                QMessageBox.warning(self, "Resume failed", str(exc))

        self._timer.start(200)
        self._refresh_state()
        self._update_controls()

    def _reset_workout(self) -> None:
        if not self._controller.is_workout_available():
            return

        self._controller.reset()
        self._timer.start(200)
        self._refresh_state()
        self._update_controls()

    def _resync_workout(self) -> None:
        if not self._controller.is_workout_available():
            QMessageBox.warning(self, "No workout", "Please load a workout before resynchronizing.")
            return

        total_duration = self._controller.get_workout.total_duration
        value, ok = QInputDialog.getDouble(
            self,
            "Resynchronize workout",
            "Workout position (seconds):",
            0.0,
            0.0,
            max(1000000.0, total_duration),
            2,
        )
        if not ok:
            return

        try:
            self._controller.resync(value)
        except Exception as exc:
            QMessageBox.warning(self, "Resync failed", str(exc))
            return

        self._timer.start(200)
        self._refresh_state()
        self._update_controls()

    def _refresh_state(self) -> None:
        if not self._controller.is_workout_available():
            self._status_label.setText("Status: no workout loaded")
            self._update_controls()
            return

        workout = self._controller.get_workout()
        state = self._controller.get_workout_state()

        if state.interval_index is None:
            self._interval_label.setText("Interval: finished")
            self._interval_detail_label.setText("Workout complete.")
        else:
            self._interval_label.setText(
                f"Interval {state.interval_index + 1} / {len(workout.intervals) if not workout is None else 0 }"
            )
            self._interval_detail_label.setText(self._format_interval_description(state.current_interval))

        self._controller.refresh_state()

        self._song_label.setText(
            f"Song: {self._controller.get_current_song_name() or 'none'}"
        )
        self._music_status_label.setText(
            f"Music: {'playing' if state.status == WorkoutStatus.RUNNING else 'paused'}"
            if self._controller.is_music_available()
            else "Music: disabled"
        )
        self._interval_time_label.setText(
            f"Interval time: {format_seconds(state.elapsed_in_interval)} / {format_seconds(state.remaining_in_interval)}"
        )
        self._workout_time_label.setText(
            f"Workout time: {format_seconds(state.total_elapsed)} / {format_seconds(workout.total_duration if not workout is None else 0.0)}"
        )

        status_text = state.status.replace("_", " ").capitalize()
        if state.status == WorkoutStatus.FINISHED:
            status_text = "Finished"
        self._status_label.setText(f"Status: {status_text}")
        self._update_controls()

        if state.status == WorkoutStatus.FINISHED:
            self._timer.stop()

    def _format_interval_description(self, interval: Optional[Interval]) -> str:
        if interval is None:
            return "No current interval."
        parts = [f"Duration: {format_seconds(interval.duration)}"]
        if getattr(interval, "power", None) is not None:
            parts.append(f"Power: {interval.power}")
        if getattr(interval, "cadence", None) is not None:
            parts.append(f"Cadence: {interval.cadence}")
        if getattr(interval, "type", None):
            parts.insert(0, f"Type: {interval.type}")
        return " · ".join(parts)

    def _update_controls(self) -> None:
        has_workout = self._controller.is_workout_available()
        status = self._controller.get_workout_state().status
        self._load_button.setEnabled(True)
        self._start_button.setEnabled(has_workout and status is WorkoutStatus.NOT_STARTED)
        if not has_workout:
            self._pause_button.setEnabled(False)
            self._pause_button.setText("Pause")
        elif status is WorkoutStatus.RUNNING:
            self._pause_button.setEnabled(True)
            self._pause_button.setText("Pause")
        elif status is WorkoutStatus.PAUSED:
            self._pause_button.setEnabled(True)
            self._pause_button.setText("Resume")
        else:
            self._pause_button.setEnabled(False)
            self._pause_button.setText("Pause")

        self._reset_button.setEnabled(has_workout)
        self._resync_button.setEnabled(has_workout)
        audio_output = self._controller.get_audio_output()
        if self._controller.is_music_available() and audio_output is not None:
            audio_output.setVolume(1.0)
            audio_output.setMuted(False)