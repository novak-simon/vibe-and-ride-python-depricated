import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ui.music_player as music_player_module
from ui.music_player import MusicPlayer


class FakePlaylist:
    Loop = 1

    def __init__(self):
        self._media = []
        self._index = -1

    def setPlaybackMode(self, mode):
        self.mode = mode

    def addMedia(self, media):
        self._media.append(media)

    def mediaCount(self):
        return len(self._media)

    def currentIndex(self):
        return self._index

    def setCurrentIndex(self, index):
        self._index = index

    def next(self):
        if self._media:
            self._index = min(self._index + 1, len(self._media) - 1)


class FakePlayer:
    def __init__(self):
        self.audio_output = None
        self.playlist = None
        self.playing = False

    def setAudioOutput(self, audio_output):
        self.audio_output = audio_output

    def setPlaylist(self, playlist):
        self.playlist = playlist

    def play(self):
        self.playing = True

    def pause(self):
        self.playing = False

    def stop(self):
        self.playing = False


class FakeAudioOutput:
    pass


class FakeUrl:
    @staticmethod
    def fromLocalFile(path: str):
        return path


class MusicPlayerTest(unittest.TestCase):
    def test_backend_unavailable_when_multimedia_missing(self):
        with patch.object(music_player_module, "QMediaPlayer", None), \
             patch.object(music_player_module, "QAudioOutput", None), \
             patch.object(music_player_module, "QMediaPlaylist", None), \
             patch.object(music_player_module, "QUrl", None):
            player = MusicPlayer(Path("."))
            self.assertFalse(player.available)
            self.assertEqual(player.debug_info, "backend unavailable")

    def test_player_initializes_and_loads_songs_when_backend_available(self):
        with patch.object(music_player_module, "QMediaPlayer", FakePlayer), \
             patch.object(music_player_module, "QAudioOutput", FakeAudioOutput), \
             patch.object(music_player_module, "QMediaPlaylist", FakePlaylist), \
             patch.object(music_player_module, "QUrl", FakeUrl):
            with tempfile.TemporaryDirectory() as temp_dir:
                song_dir = Path(temp_dir)
                (song_dir / "one.mp3").write_text("dummy")
                (song_dir / "two.wav").write_text("dummy")

                player = MusicPlayer(song_dir)
                self.assertTrue(player.available)
                self.assertEqual(len(player._songs), 2)
                self.assertEqual(player._playlist.mediaCount(), 2)
                self.assertEqual(player.debug_info, "backend OK, songs=2, media_count=2, current_index=-1")

                player.next_track()
                self.assertEqual(player.current_song_name(), "one.mp3")
                self.assertTrue(player._player.playing)

    def test_current_song_name_none_when_no_songs(self):
        with patch.object(music_player_module, "QMediaPlayer", FakePlayer), \
             patch.object(music_player_module, "QAudioOutput", FakeAudioOutput), \
             patch.object(music_player_module, "QMediaPlaylist", FakePlaylist), \
             patch.object(music_player_module, "QUrl", FakeUrl):
            with tempfile.TemporaryDirectory() as temp_dir:
                player = MusicPlayer(Path(temp_dir))
                self.assertTrue(player.available)
                self.assertEqual(player.debug_info, "backend OK, songs=0, media_count=0, current_index=-1")
                self.assertIsNone(player.current_song_name())


if __name__ == "__main__":
    unittest.main()