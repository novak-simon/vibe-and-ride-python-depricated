import unittest

from music.model import Song


class SongModelTest(unittest.TestCase):
    def test_from_dict_with_defaults(self):
        song = Song.from_dict({"title": "Test", "jamendo_id": "abc123"})
        self.assertEqual(song.title, "Test")
        self.assertEqual(song.jamendo_id, "abc123")
        self.assertIsNone(song.id)
        self.assertIsNone(song.artist)
        self.assertEqual(song.speed, 0)
        self.assertEqual(song.bpm, 0)
        self.assertEqual(song.bpm_confidence, 0)
        self.assertIsNone(song.audio_url)
        self.assertIsNone(song.download_url)

    def test_to_record_excludes_id(self):
        song = Song(
            id=1,
            title="Track",
            jamendo_id="jam123",
            artist="Artist",
            genre="Rock",
            speed=3,
            bpm=120,
            bpm_confidence=4,
        )
        expected = {
            "title": "Track",
            "artist": "Artist",
            "jamendo_id": "jam123",
            "genre": "Rock",
            "speed": 3,
            "bpm": 120,
            "bpm_confidence": 4,
        }
        self.assertEqual(song.to_record(), expected)


if __name__ == "__main__":
    unittest.main()