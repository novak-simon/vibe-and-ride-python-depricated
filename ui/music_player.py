from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

try:
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    _PYSIDE6_MULTIMEDIA_ERROR = None
except ImportError as exc:
    QUrl = QAudioOutput = QMediaPlayer = None
    _PYSIDE6_MULTIMEDIA_ERROR = exc

logger = logging.getLogger(__name__)
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}


class MusicPlayer:
    def __init__(self, songs_dir: Path):
        self._player = None
        self._audio_output = None
        self._songs: List[Path] = []
        self._current_index = -1
        self._backend_error = _PYSIDE6_MULTIMEDIA_ERROR
        self._backend_available = (
            self._backend_error is None
            and QMediaPlayer is not None
            and QAudioOutput is not None
            and QUrl is not None
        )
        self._end_of_media_status = None

        if not self._backend_available:
            logger.warning(
                "Qt Multimedia backend unavailable; music disabled: %s",
                self._backend_error,
            )
            return

        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._audio_output.setVolume(1.0)
        self._audio_output.setMuted(False)
        self._player.setAudioOutput(self._audio_output)

        self._load_songs(songs_dir)

        self._end_of_media_status = getattr(QMediaPlayer, "EndOfMedia", None)
        if self._end_of_media_status is None:
            media_status_enum = getattr(QMediaPlayer, "MediaStatus", None)
            if media_status_enum is not None:
                self._end_of_media_status = getattr(media_status_enum, "EndOfMedia", None)

        if hasattr(self._player, "mediaStatusChanged"):
            self._player.mediaStatusChanged.connect(self._on_media_status_changed)

        if hasattr(self._player, "errorOccurred"):
            self._player.errorOccurred.connect(self._on_error)

        logger.info(
            "MusicPlayer initialized: backend available=%s, songs=%d",
            self._backend_available,
            len(self._songs),
        )

    def _load_songs(self, songs_dir: Path) -> None:
        if not songs_dir.exists() or not songs_dir.is_dir():
            logger.warning("Sample song directory does not exist: %s", songs_dir)
            return

        for path in sorted(songs_dir.iterdir()):
            if path.suffix.lower() in AUDIO_EXTENSIONS:
                self._songs.append(path)

        logger.info("Loaded %d songs from %s", len(self._songs), songs_dir)

    @property
    def available(self) -> bool:
        return self._backend_available

    @property
    def audio_output(self):
        return self._audio_output

    @property
    def debug_info(self) -> str:
        if self._backend_error is not None:
            return f"backend unavailable: {self._backend_error!r}"
        return (
            f"backend OK, songs={len(self._songs)}, current_index={self._current_index}, "
            f"current_song={self.current_song_name() or 'none'}"
        )

    def _set_current_source(self) -> None:
        if (
            self._player is None
            or self._current_index < 0
            or self._current_index >= len(self._songs)
        ):
            logger.warning("No current song to set")
            return

        source = QUrl.fromLocalFile(str(self._songs[self._current_index]))
        logger.info("Setting music source: %s", source.toString())
        self._player.setSource(source)

    def play(self) -> None:
        if not self.available or self._player is None:
            return
        if self._current_index < 0 and self._songs:
            self._current_index = 0
            self._set_current_source()
        self._player.play()

    def pause(self) -> None:
        if self._player is not None:
            self._player.pause()

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()

    def next_track(self) -> None:
        if not self.available or self._player is None or not self._songs:
            return
        self._current_index = (self._current_index + 1) % len(self._songs)
        self._set_current_source()
        self._player.play()

    def current_song_name(self) -> Optional[str]:
        if self._current_index < 0 or self._current_index >= len(self._songs):
            return None
        return self._songs[self._current_index].name

    def _on_media_status_changed(self, status) -> None:
        logger.info("Media status changed: %s", status)
        if self._end_of_media_status is not None and status == self._end_of_media_status:
            self.next_track()

    def _on_error(self, error, error_string) -> None:
        logger.error("Media player error: %s %s", error, error_string)