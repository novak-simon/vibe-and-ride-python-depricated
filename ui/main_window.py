from __future__ import annotations
import logging
import json

from pathlib import Path
from typing import List, Optional

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
    QDialog,
    QPlainTextEdit,
    QDialogButtonBox,
)

from recommendation.recommender import SongRecommendation
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
        self.setWindowTitle("Music4Zwift")
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

        self._debug_button = QPushButton("Debug")
        self._debug_button.clicked.connect(self._show_current_interval_debug)

        self._workout_name_label = QLabel("No workout loaded")
        self._workout_name_label.setAlignment(Qt.AlignLeft)

        self._interval_count_label = QLabel("")
        self._interval_count_label.setAlignment(Qt.AlignLeft)

        self._interval_label = QLabel("Interval: -")
        self._interval_label.setAlignment(Qt.AlignLeft)

        self._interval_detail_label = QLabel("Current interval details will appear here.")
        self._interval_detail_label.setWordWrap(True)

        self._song_label = QLabel(
            f"Song: {'none'}"
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

        self._skip_button = QPushButton("SKIP")
        self._skip_button.clicked.connect(self._controller.skip)

        self._reset_button = QPushButton("Reset")
        self._reset_button.clicked.connect(self._reset_workout)

        self._resync_button = QPushButton("Resynchronize")
        self._resync_button.clicked.connect(self._resync_workout)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self._start_button)
        button_layout.addWidget(self._pause_button)
        button_layout.addWidget(self._skip_button)
        button_layout.addWidget(self._reset_button)
        button_layout.addWidget(self._resync_button)

        top_layout = QHBoxLayout()
        top_layout.addWidget(self._load_button)
        top_layout.addStretch(1)
        top_layout.addWidget(self._debug_button)

        layout = QVBoxLayout()
        layout.addLayout(top_layout)
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
        self._workout_name_label.setText("Loading workout...")
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
        # keep UI responsibilities only; start scheduling via scheduler object
        self._controller.start_workout()
        self._timer.start(200)
        self._refresh_state()
        self._update_controls()

    def _toggle_pause_resume(self) -> None:
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
        self._controller.reset()
        self._timer.start(200)
        self._refresh_state()
        self._update_controls()

    def _resync_workout(self) -> None:
        total_duration = self._controller.get_workout().total_duration
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
        self._controller.refresh_state()
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

        self._song_label.setText(
            f"Song: {self._controller.get_current_song().title if self._controller.get_current_song() is not None else 'none'}"
        )
        self._music_status_label.setText(
            f"Music: {'playing' if state.status == WorkoutStatus.RUNNING else 'paused'}"
            if self._controller.is_music_available()
            else "Music: disabled"
        )
        self._interval_time_label.setText(
            f"Interval time: {format_seconds(state.elapsed_in_interval)} / {format_seconds(state.interval_length)}"
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
        status = self._controller.get_workout_state().status
        self._load_button.setEnabled(True)
        self._start_button.setEnabled(status is WorkoutStatus.NOT_STARTED)

        self._skip_button.setEnabled(status in (WorkoutStatus.RUNNING, WorkoutStatus.PAUSED))

        if status is WorkoutStatus.RUNNING:
            self._pause_button.setEnabled(True)
            self._pause_button.setText("Pause")
        elif status is WorkoutStatus.PAUSED:
            self._pause_button.setEnabled(True)
            self._pause_button.setText("Resume")
        else:
            self._pause_button.setEnabled(False)
            self._pause_button.setText("Pause")

        self._reset_button.setEnabled(status in (WorkoutStatus.RUNNING, WorkoutStatus.PAUSED, WorkoutStatus.FINISHED))
        self._resync_button.setEnabled(status in (WorkoutStatus.RUNNING, WorkoutStatus.PAUSED))
        audio_output = self._controller.get_audio_output()
        if self._controller.is_music_available() and audio_output is not None:
            audio_output.setVolume(1.0)
            audio_output.setMuted(False)

    def _show_current_interval_debug(self) -> None:
        info = self._controller.get_current_interval_debug_info()
        if not info:
            QMessageBox.information(
                self,
                "Recommendation Debug",
                "No debug info available for current interval yet.",
            )
            return

        text = self._format_interval_debug_text(info)

        dlg = QDialog(self)
        dlg.setWindowTitle("Recommendation Debug (Current Interval)")
        dlg.resize(920, 640)

        layout = QVBoxLayout(dlg)
        editor = QPlainTextEdit(dlg)
        editor.setReadOnly(True)
        editor.setPlainText(text)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=dlg)
        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(dlg.accept)

        layout.addWidget(editor)
        layout.addWidget(buttons)
        dlg.exec()

    def _format_interval_debug_text(self, info: List[SongRecommendation]) -> str:
        def _fmt(v):
            return "-" if v is None else str(v)

        def _fmt4(v):
            try:
                return f"{float(v):.4f}"
            except Exception:
                return "-"

        lines = []

        lines.append("WORKOUT / INTERVAL")
        lines.append(f"- Interval: {_fmt(self._controller.get_workout_state().interval_index)}")
        lines.append(f"- Type: {_fmt(self._controller.get_workout_state().current_interval.type if self._controller.get_workout_state().current_interval else None)}")
        lines.append(f"- Duration: {_fmt(self._controller.get_workout_state().interval_length)}")
        lines.append(f"- Target cadence: {_fmt(self._controller.get_workout_state().current_interval.cadence if self._controller.get_workout_state().current_interval else None)}")
        lines.append(f"- Target power: {_fmt(self._controller.get_workout_state().current_interval.power if self._controller.get_workout_state().current_interval else None)}")
        lines.append("")

        # New payload shape: selected_* on interval root
        lines.append("SELECTED SONGS")
        for c in info:
            lines.append(f"- Song ID: {_fmt(c.song.id)}")
            lines.append(f"- Title: {_fmt(c.song.title)}")
            lines.append(f"- Artist: {_fmt(c.song.artist)}")
            lines.append(f"- BPM: {_fmt(c.song.bpm)}")
            lines.append(f"- BPM confidence: {_fmt(c.song.bpm_confidence)}")
            lines.append(f"- Algorithm cadence: {_fmt(c.song.algorithm_cadence)}")
            lines.append(f"- Start time: {_fmt(c.song.start_time)}")
            lines.append(f"- Genre: {_fmt(c.song.genre)}")
            lines.append(f"Preference score: {_fmt4(c.preference_recommendation.score)}")
            lines.append(f"- Number of matching genres: {_fmt(c.preference_recommendation.number_of_matching_genres)}")
            lines.append(f"- Like coefficient: {_fmt(c.preference_recommendation.like_coefficient)}")
            lines.append(f"- Repetition coefficient: {_fmt(c.preference_recommendation.repetition_coefficient)}")
            lines.append(f"- Skip coefficient: {_fmt(c.preference_recommendation.skip_coefficient)}")
            lines.append(f"Interval score: {_fmt4(c.interval_recommendation.score)}")
            lines.append(f"- Cadence score: {_fmt4(c.interval_recommendation.cadence_score)}")
            lines.append(f"- Confidence score: {_fmt4(c.interval_recommendation.conf_score)}")
            lines.append(f"- Song score: {_fmt4(c.interval_recommendation.song_score)}")
            lines.append(f"FINAL SCORE: {_fmt4(c.score)}")
            lines.append("-" * 40)
        return "\n".join(lines)