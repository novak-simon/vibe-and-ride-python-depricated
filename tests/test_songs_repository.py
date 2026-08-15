import unittest
from unittest.mock import MagicMock, patch

from database.songs import Song, add_song, get_song_by_jamendo_id, get_songs, jamendo_id_exists
from music.model import Song


class SongsRepositoryTest(unittest.TestCase):
    def setUp(self):
        patcher = patch("database.songs.supabase")
        self.mock_supabase = patcher.start()
        self.addCleanup(patcher.stop)

        self.mock_query = MagicMock()
        self.mock_supabase.table.return_value = self.mock_query
        self.mock_query.select.return_value = self.mock_query
        self.mock_query.eq.return_value = self.mock_query
        self.mock_query.limit.return_value = self.mock_query
        self.mock_query.offset.return_value = self.mock_query
        self.mock_query.insert.return_value = self.mock_query

    def test_get_song_by_jamendo_id(self):
        self.mock_query.execute.return_value = {
            "data": [
                {
                    "id": 1,
                    "title": "Song",
                    "artist": "Artist",
                    "jamendo_id": "jam123",
                    "genre": "Rock",
                    "speed": 2,
                    "bpm": 100,
                    "bpm_confidence": 1,
                }
            ]
        }

        song = get_song_by_jamendo_id("jam123")

        self.mock_supabase.table.assert_called_once_with("songs")
        self.mock_query.eq.assert_called_once_with("jamendo_id", "jam123")
        self.assertEqual(song.jamendo_id, "jam123")
        self.assertEqual(song.title, "Song")

    def test_jamendo_id_exists_returns_true(self):
        self.mock_query.execute.return_value = {"data": [{"id": 1}]}
        self.assertTrue(jamendo_id_exists("jam123"))

    def test_add_song_inserts_new_song(self):
        self.mock_query.execute.side_effect = [
            {"data": []},
            {
                "data": [
                    {
                        "id": 2,
                        "title": "New Song",
                        "artist": None,
                        "jamendo_id": "jam234",
                        "genre": None,
                        "speed": 0,
                        "bpm": 0,
                        "bpm_confidence": 0,
                    }
                ]
            },
        ]

        song = Song(title="New Song", jamendo_id="jam234")
        inserted = add_song(song)

        self.assertEqual(inserted.id, 2)
        self.assertEqual(inserted.title, "New Song")

    def test_add_song_raises_for_duplicate_jamendo_id(self):
        self.mock_query.execute.return_value = {"data": [{"id": 3}]}
        with self.assertRaises(ValueError):
            add_song(Song(title="Song", jamendo_id="jam123"))

    def test_get_songs_returns_list(self):
        self.mock_query.execute.return_value = {
            "data": [
                {"id": 1, "title": "A", "jamendo_id": "a"},
                {"id": 2, "title": "B", "jamendo_id": "b"},
            ]
        }

        songs = get_songs(limit=2, offset=10)

        self.mock_query.limit.assert_called_once_with(2)
        self.mock_query.offset.assert_called_once_with(10)
        self.assertEqual(len(songs), 2)
        self.assertEqual(songs[0].title, "A")


if __name__ == "__main__":
    unittest.main()
