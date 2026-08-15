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

from database.user_song_stats import increment_stat, set_stat_datetime
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
            print(f"Initial song: {self._provider.get_current_song().title if self._provider.get_current_song() else 'None'}")
            self._set_current_source()

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

    @property
    def time_remaining(self) -> Optional[float]:
        if self._player is None or not self._backend_available:
            return None
        duration_ms = self._player.duration()
        position_ms = self._player.position()
        if duration_ms < 0 or position_ms < 0:
            return None
        return (duration_ms - position_ms) / 1000.0

    @property
    def time_elapsed(self) -> Optional[float]:
        if self._player is None or not self._backend_available:
            return None
        position_ms = self._player.position()
        starting_time = self._current_song.start_time if self._current_song else 0
        time_elapsed = position_ms / 1000.0 - starting_time
        return time_elapsed if time_elapsed >= 0 else 0.0

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

        print(f"Song: {self._current_song.title}, ID: {self._current_song.id}, BPM: {self._current_song.bpm}, Genre: {self._current_song.genre}, Start time: {self._current_song.start_time}")
        increment_stat(stat="play_count", song_id=self.current_song().id, user_id=None, client=self.admin_client)
        set_stat_datetime(stat="last_played_at", song_id=self.current_song().id, user_id=None, client=self.admin_client)

    def current_song(self) -> Optional[Song]:
        return self._current_song

    def play(self) -> None:
        if not self.available or self._player is None:
            return
        if not self._player.source().isValid() and self._provider.has_songs():
            print("Invalid source, loading new song")
            self._provider._current_index = 0
            self._set_current_source()
        self._player.play()

    def pause(self) -> None:
        if self._player is not None:
            self._player.pause()

    def stop(self) -> None:
        if self._player is not None:
            increment_stat(stat="total_play_time", song_id=self.current_song().id, user_id=None, client=self.admin_client, increment_by=int(self.time_elapsed or 0))
            self._player.stop()
            print(f"song id: {self.current_song().id if self.current_song() else 'None'}, time elapsed: {self.time_elapsed if self.time_elapsed is not None else 'None'}")
            

    def next_track(self, interval_changed: bool = False) -> None:
        if not self.available or self._player is None or not self._provider.has_songs():
            return
        if self._current_song is not None:
            increment_stat(stat="total_play_time", song_id=self.current_song().id, user_id=None, client=self.admin_client, increment_by=int(self.time_elapsed or 0))
        next_song = self._provider.next_song(interval_changed)
        print(f"Next track: {next_song.title if next_song else 'None'}")
        self._set_current_source(next_song)
        self._player.play()

    def next_interval_soon(self) -> None:
        self._provider.precompute_recommendations(self._provider.scheduler.workout, self._provider.scheduler.current_interval_index() + 1)
        

    def _on_media_status_changed(self, status) -> None:
        print(f"Media status changed: {status}")
        logger.info("Media status changed: %s", status)
        if status is QMediaPlayer.MediaStatus.LoadedMedia:
            self._player.setPosition(int(self._current_song.start_time * 1000))
        if status is QMediaPlayer.MediaStatus.EndOfMedia:
            print("End of media reached")
            self.next_track()

    def _on_error(self, error, error_string) -> None:
        logger.error("Media player error: %s %s", error, error_string)

    def workout_chosen(self, workout: Workout):
        print(f"Workout chosen: {workout.name if workout else 'None'}")
        self._provider.precompute_recommendations(workout, self._provider.scheduler.current_interval_index())