from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

try:
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    _PYSIDE6_MULTIMEDIA_ERROR = None
except ImportError as exc:
    QUrl = QAudioOutput = QMediaPlayer = None
    _PYSIDE6_MULTIMEDIA_ERROR = exc

from database.user_song_stats import increment_stat
from database.admin_client import create_admin_supabase
from music.model import Song
from music.provider import SongProvider
from workout.scheduler import WorkoutScheduler
from workout.model import Workout

logger = logging.getLogger(__name__)

MUSIC_ENABLED = True


class MusicPlayer:
    def __init__(self, scheduler: WorkoutScheduler, *args, **kwargs) -> None:
        self._player = None
        self._audio_output = None
        self._provider = SongProvider(scheduler=scheduler)
        self._songs = self._provider._songs
        self._current_song = None
        self._debug_info = ""
        self._backend_error = _PYSIDE6_MULTIMEDIA_ERROR
        self._backend_available = (
            QMediaPlayer is not None
            and QAudioOutput is not None
            and QUrl is not None
        )
        self._end_of_media_status = None
        self.admin_client = create_admin_supabase()

        if not self._backend_available:
            logger.warning(
                "Qt Multimedia backend unavailable; music disabled: %s",
                self._backend_error,
            )
            return

        self._player = getattr(self, "_player", None) or QMediaPlayer()
        self._audio_output = getattr(self, "_audio_output", None) or QAudioOutput()
        # default to 80% volume; adjust if you prefer quieter/louder
        try:
            self._audio_output.setVolume(0.8)
        except Exception:
            # older Qt bindings may expect volume in a different range; ignore if unsupported
            pass
        # attach audio output to player
        try:
            self._player.setAudioOutput(self._audio_output)
        except Exception:
            # some environments may already have audio routing set; continue
            pass

        # optional: log player errors
        try:
            self._player.errorOccurred.connect(
                lambda err, msg=None: logger.error("QMediaPlayer error: %s %s", err, msg)
            )
        except Exception:
            # signal may not be present in some bindings; ignore
            pass

        if self._provider.has_songs():
            self._set_current_source()

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

    @property
    def available(self) -> bool:
        return self._backend_available

    @property
    def audio_output(self):
        return self._audio_output

    @property
    def debug_info(self) -> str:
        if not self._backend_available:
            return "backend unavailable"
        return (
            f"backend OK, songs={len(self._songs)}"
        )

    def get_provider(self) -> SongProvider:
        return None if self._provider is None else self._provider

    def _set_current_source(self, song: Song = None) -> None:

        if song is None:
            song = self._provider.get_current_song()
        if song is None or song.audio_url is None or QUrl is None:
            return

        if song.audio_url.startswith(("http://", "https://")):
            source = QUrl(song.audio_url)
        else:
            source = QUrl.fromLocalFile(song.audio_url)
        self._current_song = song
        if hasattr(self._player, "setSource"):
            self._player.setSource(source)

    def current_song(self) -> Optional[Song]:
        return self._current_song

    def play(self) -> None:
        if not self.available or self._player is None:
            return
        if self._provider.get_current_song() is None and self._provider.has_songs():
            self._provider._current_index = 0
            self._set_current_source()
        self._player.play()

    def pause(self) -> None:
        if self._player is not None:
            self._player.pause()

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()

    def next_track(self, interval_changed: bool = False) -> None:
        if not self.available or self._player is None or not self._provider.has_songs():
            return
        next_song = self._provider.next_song(interval_changed)
        self._set_current_source(next_song)
        self._player.play()

    def _on_media_status_changed(self, status) -> None:
        logger.info("Media status changed: %s", status)
        if status is QMediaPlayer.MediaStatus.LoadedMedia:
            print("Loaded Media")
            print(f"Song: {self._current_song.title}, ID: {self._current_song.id}, BPM: {self._current_song.bpm}, Genre: {self._current_song.genre}, Start time: {self._current_song.start_time}")
            print(f"Start time planned: {self._current_song.start_time}")
            self._player.setPosition(int(self._current_song.start_time * 1000))
            increment_stat(stat="play_count", song_id=self.current_song().id, user_id=None, client=self.admin_client)
            print(f"Position {self._player.position()}")
        if self._end_of_media_status is not None and status == self._end_of_media_status:
            self.next_track()

    def _on_error(self, error, error_string) -> None:
        logger.error("Media player error: %s %s", error, error_string)

    def workout_chosen(self, workout: Workout):
        self._provider.precompute_recommendations(workout)