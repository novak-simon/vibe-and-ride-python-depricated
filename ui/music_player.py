from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

try:
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QMediaPlaylist
    _PYSIDE6_MULTIMEDIA_ERROR = None
except ImportError as exc:
    QAudioOutput = QMediaPlayer = QMediaPlaylist = QUrl = None
    _PYSIDE6_MULTIMEDIA_ERROR = exc

logger = logging.getLogger(__name__)
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}


class MusicPlayer:
    def __init__(self, songs_dir: Path):
        self._player = None
        self._playlist = None
        self._songs: List[Path] = []
        self._enabled = False
        self._backend_error = _PYSIDE6_MULTIMEDIA_ERROR
        self._backend_available = (
            self._backend_error is None
            and QMediaPlayer is not None
            and QAudioOutput is not None
            and QMediaPlaylist is not None
        )

        if not self._backend_available:
            logger.warning(
                "Qt Multimedia backend unavailable; music disabled: %s",
                self._backend_error,
            )
            return

        self._playlist = QMediaPlaylist()
        self._playlist.setPlaybackMode(QMediaPlaylist.Loop)

        self._player = QMediaPlayer()
        audio_output = QAudioOutput()
        self._player.setAudioOutput(audio_output)
        self._player.setPlaylist(self._playlist)

        self._load_songs(songs_dir)
        self._enabled = True
        logger.info("MusicPlayer initialized: backend available=%s, songs=%d",
                    self._backend_available, len(self._songs))

    def _load_songs(self, songs_dir: Path) -> None:
        if not songs_dir.exists() or not songs_dir.is_dir():
            logger.warning("Sample song directory does not exist: %s", songs_dir)
            return

        for path in sorted(songs_dir.iterdir()):
            if path.suffix.lower() in AUDIO_EXTENSIONS:
                self._playlist.addMedia(QUrl.fromLocalFile(str(path)))
                self._songs.append(path)

        logger.info("Loaded %d songs from %s", len(self._songs), songs_dir)

    @property
    def available(self) -> bool:
        return self._backend_available

    @property
    def debug_info(self) -> str:
        if self._backend_error is not None:
            return f"backend unavailable: {self._backend_error!r}"
        media_count = self._playlist.mediaCount() if self._playlist is not None else 0
        current_index = self._playlist.currentIndex() if self._playlist is not None else -1
        return (
            f"backend OK, songs={len(self._songs)}, media_count={media_count}, "
            f"current_index={current_index}"
        )

    def play(self) -> None:
        if not self.available or self._player is None:
            return
        if self._playlist.mediaCount() > 0 and self._playlist.currentIndex() < 0:
            self._playlist.setCurrentIndex(0)
        self._player.play()

    def pause(self) -> None:
        if self._player is not None:
            self._player.pause()

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()

    def next_track(self) -> None:
        if not self.available or self._playlist is None:
            return
        if self._playlist.mediaCount() == 0:
            return
        if self._playlist.currentIndex() < 0:
            self._playlist.setCurrentIndex(0)
        else:
            self._playlist.next()
        self._player.play()

    def current_song_name(self) -> Optional[str]:
        if not self.available or self._playlist is None:
            return None
        index = self._playlist.currentIndex()
        if index < 0 or index >= len(self._songs):
            return None
        return self._songs[index].name