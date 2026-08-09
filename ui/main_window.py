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
from music.player import MusicPlayer
from database.workouts import upload_parsed_file

logger = logging.getLogger(__name__)

def _optional_float(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return float(value)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Zwift Music")
        self.scheduler: Optional[WorkoutScheduler] = None
        self._music_player = MusicPlayer(self._sample_song_dir())
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_state)
        self._timer.start(200)

    def _sample_song_dir(self) -> Path:
        return Path(__file__).resolve().parents[1] / "assets" / "sample_songs"

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
            f"Song: {self._music_player.current_song_name() or 'none'}"
        )
        self._song_label.setWordWrap(True)
        self._music_status_label = QLabel(
            f"Music: {'enabled' if self._music_player.available else 'disabled'}"
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
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select workout file",
            "",
            "Workout files (*.json *.zwo);;JSON files (*.json);;Zwift workout files (*.zwo)",
        )
        if not path:
            return

        try:
            workout = self._load_workout_file(Path(path))
            self.scheduler = WorkoutScheduler(workout)
            self._workout_name_label.setText(f"Workout: {workout.name or 'Unnamed'}")
            self._interval_count_label.setText(f"{len(workout.intervals)} intervals")
            self._refresh_state()
            self._update_controls()
        except Exception as exc:
            QMessageBox.critical(self, "Workout load failed", str(exc))

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

    def _extract_intervals_from_node(self, node: dict) -> list[Interval]:
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

        return [
            Interval(
                duration=float(duration),
                power=_optional_float(interval_info.get("power")),
                cadence=_optional_float(interval_info.get("cadence")),
                type=node.get("type"),
                attrs=dict(node.get("attrs", {}) or {}),
            )
        ]

    def _intervals_from_intervals_t(self, attrs: dict) -> list[Interval]:
        repeat = int(attrs.get("Repeat") or 1)
        on_duration = attrs.get("OnDuration")
        off_duration = attrs.get("OffDuration")
        on_power = _optional_float(attrs.get("OnPower"))
        off_power = _optional_float(attrs.get("OffPower"))
        cadence = _optional_float(attrs.get("Cadence"))

        intervals = []
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

    def _start_workout(self) -> None:
        if self.scheduler is None:
            QMessageBox.warning(self, "No workout", "Please load a workout before starting.")
            return

        self.scheduler.start()
        self._timer.start(200)
        self._refresh_state()
        self._update_controls()

    def _toggle_pause_resume(self) -> None:
        if self.scheduler is None:
            return

        if self.scheduler.is_running:
            try:
                self.scheduler.pause()
            except Exception as exc:
                QMessageBox.warning(self, "Pause failed", str(exc))
        elif self.scheduler.is_paused:
            try:
                self.scheduler.resume()
            except Exception as exc:
                QMessageBox.warning(self, "Resume failed", str(exc))

        self._timer.start(200)
        self._refresh_state()
        self._update_controls()

    def _reset_workout(self) -> None:
        if self.scheduler is None:
            return

        self.scheduler.reset()
        self._timer.start(200)
        self._refresh_state()
        self._update_controls()

    def _resync_workout(self) -> None:
        if self.scheduler is None:
            QMessageBox.warning(self, "No workout", "Please load a workout before resynchronizing.")
            return

        total_duration = self.scheduler.workout.total_duration
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
            self.scheduler.resync(value)
        except Exception as exc:
            QMessageBox.warning(self, "Resync failed", str(exc))
            return

        self._timer.start(200)
        self._refresh_state()
        self._update_controls()

    def _refresh_state(self) -> None:
        if self.scheduler is None:
            self._status_label.setText("Status: no workout loaded")
            self._update_controls()
            return

        state = self.scheduler.get_state()

        if state.interval_index is None:
            self._interval_label.setText("Interval: finished")
            self._interval_detail_label.setText("Workout complete.")
        else:
            self._interval_label.setText(
                f"Interval {state.interval_index + 1} / {len(self.scheduler.workout.intervals)}"
            )
            self._interval_detail_label.setText(self._format_interval_description(state.current_interval))

        if state.status == WorkoutStatus.RUNNING:
            if state.interval_changed:
                self._music_player.next_track()
            self._music_player.play()
        elif state.status == WorkoutStatus.PAUSED or state.status == WorkoutStatus.NOT_STARTED:
            self._music_player.pause()
        else:
            self._music_player.stop()

        self._song_label.setText(
            f"Song: {self._music_player.current_song_name() or 'none'}"
        )
        self._music_status_label.setText(
            f"Music: {'playing' if state.status == WorkoutStatus.RUNNING else 'paused'}"
            if self._music_player.available
            else "Music: disabled"
        )
        self._interval_time_label.setText(
            f"Interval time: {format_seconds(state.elapsed_in_interval)} / {format_seconds(state.remaining_in_interval)}"
        )
        self._workout_time_label.setText(
            f"Workout time: {format_seconds(state.total_elapsed)} / {format_seconds(self.scheduler.workout.total_duration)}"
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
        has_workout = self.scheduler is not None
        self._load_button.setEnabled(True)
        self._start_button.setEnabled(has_workout and self.scheduler.status == WorkoutStatus.NOT_STARTED)
        if not has_workout:
            self._pause_button.setEnabled(False)
            self._pause_button.setText("Pause")
        elif self.scheduler.is_running:
            self._pause_button.setEnabled(True)
            self._pause_button.setText("Pause")
        elif self.scheduler.is_paused:
            self._pause_button.setEnabled(True)
            self._pause_button.setText("Resume")
        else:
            self._pause_button.setEnabled(False)
            self._pause_button.setText("Pause")

        self._reset_button.setEnabled(has_workout)
        self._resync_button.setEnabled(has_workout)

        if self._music_player.available and self._music_player.audio_output is not None:
            self._music_player.audio_output.setVolume(1.0)
            self._music_player.audio_output.setMuted(False)

    def _set_current_source(self) -> None:
        if self._current_index < 0 or self._current_index >= len(self._songs):
            logger.warning("No current song to set")
            return
        source = QUrl.fromLocalFile(str(self._songs[self._current_index]))
        logger.info("Setting music source: %s", source.toString())
        self._player.setSource(source)

    def _on_media_status_changed(self, status) -> None:
        logger.info("Media status changed: %s", status)
        if self._end_of_media_status is not None and status == self._end_of_media_status:
            self.next_track()

    def _on_error(self, error, error_string):
        logger.error("Media player error: %s %s", error, error_string)