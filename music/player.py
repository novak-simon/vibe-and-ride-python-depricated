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

from music.model import Song
from music.provider import SongProvider

logger = logging.getLogger(__name__)

MUSIC_ENABLED = True


class MusicPlayer:
    def __init__(self, *args, **kwargs) -> None:
        self._player = None
        self._audio_output = None
        self._provider = SongProvider()
        self._songs = self._provider.songs()
        self._current_index = self._provider._current_index
        self._debug_info = ""
        self._backend_error = _PYSIDE6_MULTIMEDIA_ERROR
        self._backend_available = (
            QMediaPlayer is not None
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
            f"backend OK, songs={len(self._songs)}, "
            f"current_index={self._current_index}"
        )

    def get_provider(self) -> SongProvider:
        return self._provider

    def _set_current_source(self) -> None:
        song = self._provider.get_current_song()
        if song is None or song.audio_url is None or QUrl is None:
            return

        if song.audio_url.startswith(("http://", "https://")):
            source = QUrl(song.audio_url)
        else:
            source = QUrl.fromLocalFile(song.audio_url)

        if hasattr(self._player, "setSource"):
            self._player.setSource(source)

    def current_song_name(self) -> Optional[str]:
        song = self._provider.get_current_song()
        if song is None or not song.title:
            return None
        if song.artist:
            return f"{song.title} — {song.artist}"
        return song.title

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

    def next_track(self) -> None:
        if not self.available or self._player is None or not self._provider.has_songs():
            return
        self._provider.next_song()
        self._songs = self._provider.songs()
        self._current_index = self._provider._current_index
        self._set_current_source()
        self._player.play()

    def _on_media_status_changed(self, status) -> None:
        logger.info("Media status changed: %s", status)
        if self._end_of_media_status is not None and status == self._end_of_media_status:
            self.next_track()

    def _on_error(self, error, error_string) -> None:
        logger.error("Media player error: %s %s", error, error_string)

    # ensure playback uses setSource with a QUrl and audio output is unmuted
    def play_path(self, path: str) -> None:
        if not path or not isinstance(path, str):
            return
        if not path.startswith(("http://", "https://", "file://")):
            path = "file://" + path
        try:
            url = QUrl.fromLocalFile(str(path))
            # attach source and play
            try:
                self._player.setSource(url)
            except Exception:
                # older API compatibility
                try:
                    from PySide6.QtMultimedia import QMediaContent
                    self._player.setSource(QMediaContent(url))
                except Exception:
                    pass
            # ensure volume is non-zero and unmuted
            try:
                if self._audio_output is not None:
                    # set a sensible default if volume was 0
                    if self._audio_output.volume() == 0:
                        self._audio_output.setVolume(0.8)
            except Exception:
                pass
            self._player.play()
        except Exception:
            logger.exception("Failed to play path: %s", path)