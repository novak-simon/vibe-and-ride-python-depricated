from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

try:
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QMediaPlaylist
    _QT_MULTIMEDIA_ERROR = None
except ImportError:
    try:
        from PySide2.QtCore import QUrl
        from PySide2.QtMultimedia import QAudioOutput, QMediaPlayer, QMediaPlaylist
        _QT_MULTIMEDIA_ERROR = None
    except ImportError as exc:
        QUrl = QAudioOutput = QMediaPlayer = QMediaPlaylist = None
        _QT_MULTIMEDIA_ERROR = exc

from database.client import supabase
from database.songs import get_playable_songs
from music.model import Song


logger = logging.getLogger(__name__)

MUSIC_ENABLED = True


class MusicPlayer:
    def __init__(self, song_directory: Path, *args, **kwargs) -> None:
        self._player = None
        self._audio_output = None
        self._playlist = None
        self._songs: List[Song] = []
        self._current_index = -1
        self._debug_info = ""

        self._backend_available = self._is_backend_available() and MUSIC_ENABLED

        if self._backend_available:
            self._load_songs_from_database()
            if not self._songs:
                self._load_local_songs(song_directory)

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