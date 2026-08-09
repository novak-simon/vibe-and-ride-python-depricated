from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from database.client import supabase
from database.songs import get_playable_songs
from music.model import Song

AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}


class SongProvider:
    def __init__(self, song_directory: Path, client=None) -> None:
        self._song_directory = song_directory
        self._client = client or supabase
        self._songs: List[Song] = []
        self._current_index = -1
        self._load_songs()

    def _load_songs(self) -> None:
        try:
            songs = get_playable_songs(client=self._client)
        except Exception:
            songs = []

        if not songs:
            songs = self._load_local_songs()

        self._songs = songs
        self._current_index = 0 if self._songs else -1

    def _load_local_songs(self) -> List[Song]:
        if not self._song_directory.exists() or not self._song_directory.is_dir():
            return []

        songs: List[Song] = []
        for path in sorted(self._song_directory.iterdir()):
            if path.suffix.lower() not in AUDIO_EXTENSIONS:
                continue

            songs.append(
                Song(
                    title=path.stem,
                    jamendo_id=f"local-{path.name}",
                    audio_url=str(path),
                )
            )
        return songs

    def has_songs(self) -> bool:
        return bool(self._songs)

    def get_current_song(self) -> Optional[Song]:
        if self._current_index < 0 or self._current_index >= len(self._songs):
            return None
        return self._songs[self._current_index]

    def next_song(self) -> Optional[Song]:
        if not self._songs:
            return None
        self._current_index = (self._current_index + 1) % len(self._songs)
        return self.get_current_song()

    def songs(self) -> List[Song]:
        return list(self._songs)