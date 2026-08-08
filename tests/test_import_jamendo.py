import unittest

from tools.jamendo_importer import (
    SPEED_MAP,
    jamendo_result_to_song,
    jamendo_speed_to_int,
)


class JamendoImporterTest(unittest.TestCase):
    def test_convert_normal_track(self):
        result = {
            "id": "123",
            "name": "Test Track",
            "artist_name": "Test Artist",
            "musicinfo": {
                "speed": "high",
                "tags": {"genres": ["rock"]},
            },
        }

        song = jamendo_result_to_song(result)

        self.assertEqual(song.title, "Test Track")
        self.assertEqual(song.artist, "Test Artist")
        self.assertEqual(song.jamendo_id, "123")
        self.assertEqual(song.genre, "rock")
        self.assertEqual(song.speed, 4)
        self.assertEqual(song.bpm, 0)
        self.assertEqual(song.bpm_confidence, 0)

    def test_multiple_genres_concatenated(self):
        result = {
            "id": "123",
            "name": "Test Track",
            "artist_name": "Artist",
            "musicinfo": {
                "speed": "medium",
                "tags": {"genres": ["rock", "pop"]},
            },
        }

        song = jamendo_result_to_song(result)
        self.assertEqual(song.genre, "rock,pop")
        self.assertEqual(song.speed, 2)

    def test_missing_genres_becomes_none(self):
        result = {
            "id": "123",
            "name": "Test Track",
            "artist_name": "Artist",
            "musicinfo": {"speed": "low"},
        }

        song = jamendo_result_to_song(result)
        self.assertIsNone(song.genre)
        self.assertEqual(song.speed, 1)

    def test_missing_speed_defaults_to_zero(self):
        result = {
            "id": "123",
            "name": "Test Track",
            "artist_name": "Artist",
            "musicinfo": {"tags": {"genres": ["electronic"]}},
        }

        song = jamendo_result_to_song(result)
        self.assertEqual(song.speed, 0)

    def test_unknown_speed_value_becomes_zero(self):
        self.assertEqual(jamendo_speed_to_int("superfast"), 0)

    def test_missing_artist_is_none(self):
        result = {
            "id": "123",
            "name": "Test Track",
            "musicinfo": {"speed": "high", "tags": {"genres": ["rock"]}},
        }

        song = jamendo_result_to_song(result)
        self.assertIsNone(song.artist)

    def test_missing_required_fields_raises(self):
        with self.assertRaises(ValueError):
            jamendo_result_to_song({"name": "Test Track"})

    def test_audio_and_download_urls_present(self):
        result = {
            "id": "2273291",
            "name": "Example Song",
            "artist_name": "Example Artist",
            "audio": "https://audio.example/stream.mp3",
            "audiodownload": "https://audio.example/download.mp3",
            "musicinfo": {},
        }
        song = jamendo_result_to_song(result)
        self.assertEqual(song.audio_url, "https://audio.example/stream.mp3")
        self.assertEqual(song.download_url, "https://audio.example/download.mp3")

    def test_missing_audio_sets_audio_url_none(self):
        result = {
            "id": "2273292",
            "name": "No Audio",
            "artist_name": "Artist",
            "audiodownload": "https://audio.example/download.mp3",
            "musicinfo": {},
        }
        song = jamendo_result_to_song(result)
        self.assertIsNone(song.audio_url)
        self.assertEqual(song.download_url, "https://audio.example/download.mp3")

    def test_missing_audiodownload_sets_download_url_none(self):
        result = {
            "id": "2273293",
            "name": "No Download",
            "artist_name": "Artist",
            "audio": "https://audio.example/stream.mp3",
            "musicinfo": {},
        }
        song = jamendo_result_to_song(result)
        self.assertEqual(song.audio_url, "https://audio.example/stream.mp3")
        self.assertIsNone(song.download_url)