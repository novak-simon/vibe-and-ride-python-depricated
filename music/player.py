from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

QMediaPlaylist = None

try:
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    _PYSIDE6_MULTIMEDIA_ERROR = None
except ImportError as exc:
    QUrl = QAudioOutput = QMediaPlayer = None
    _PYSIDE6_MULTIMEDIA_ERROR = exc

from database.client import supabase
from database.songs import get_playable_songs
from music.model import Song


logger = logging.getLogger(__name__)

MUSIC_ENABLED = True
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}

class MusicPlayer:
    def __init__(self, song_directory: Path, *args, **kwargs) -> None:
        self._player = None
        self._audio_output = None
        self._playlist = None
        self._songs: List[Song] = []
        self._current_index = -1
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
        
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        if hasattr(self._audio_output, "setVolume"):
            self._audio_output.setVolume(1.0)
        if hasattr(self._audio_output, "setMuted"):
            self._audio_output.setMuted(False)
        self._player.setAudioOutput(self._audio_output)

        if hasattr(self._player, "setPlaylist"):
            self._player.setPlaylist(self._playlist)

        if self._backend_available:
            self._load_songs_from_database()
            if not self._songs:
                self._load_local_songs(song_directory)

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

    def _load_songs_from_database(self) -> None:
        try:
            songs = get_playable_songs(client=supabase)
        except Exception as exc:
            logger.exception("Could not load songs from Supabase")
            self._database_error = exc
            return

        if not songs:
            return

        self._songs = songs
        for song in songs:
            self._add_song_source(song)

        self._current_index = 0

    def _load_local_songs(self, song_directory: Path) -> None:
        if not song_directory.exists() or not song_directory.is_dir():
            return

        for path in sorted(song_directory.iterdir()):
            if path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue

            song = Song(
                title=path.stem,
                jamendo_id=f"local-{path.name}",
                audio_url=str(path),
            )
            self._songs.append(song)
            self._add_song_source(song)

        if self._songs:
            self._current_index = 0

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
        media_count = 0
        if self._playlist is not None and hasattr(self._playlist, "mediaCount"):
            media_count = self._playlist.mediaCount()
        return (
            f"backend OK, songs={len(self._songs)}, media_count={media_count}, "
            f"current_index={self._current_index}"
        )

    def _add_song_source(self, song: Song) -> None:
        if self._playlist is None or song.audio_url is None or QUrl is None:
            return

        if song.audio_url.startswith(("http://", "https://")):
            source = QUrl(song.audio_url)
        else:
            source = QUrl.fromLocalFile(song.audio_url)

        if hasattr(self._playlist, "addMedia"):
            self._playlist.addMedia(source)
        elif hasattr(self._playlist, "addSource"):
            self._playlist.addSource(source)

    def current_song_name(self) -> Optional[str]:
        if self._current_index < 0 or self._current_index >= len(self._songs):
            return None
        song = self._songs[self._current_index]
        if not song.title:
            return None
        if song.artist:
            return f"{song.title} — {song.artist}"
        return song.title

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

    def _on_media_status_changed(self, status) -> None:
        logger.info("Media status changed: %s", status)
        if self._end_of_media_status is not None and status == self._end_of_media_status:
            self.next_track()

    def _on_error(self, error, error_string) -> None:
        logger.error("Media player error: %s %s", error, error_string)