import unittest
from unittest.mock import MagicMock, patch

from music.model import Song
import tools.jamendo_importer as importer


class ImporterAdminClientTest(unittest.TestCase):
    def test_importer_passes_admin_client_to_repository(self):
        fake_admin_client = object()

        with patch.object(importer, "get_admin_supabase", return_value=fake_admin_client), patch(
            "database.songs.jamendo_id_exists", return_value=False
        ) as exists_mock, patch(
            "database.songs.add_song", return_value=Song(title="Imported", jamendo_id="123")
        ) as add_mock:
            stats = importer.import_jamendo_tracks(
                [
                    {
                        "id": "123",
                        "name": "Imported",
                        "artist_name": "Importer",
                        "musicinfo": {"speed": "medium", "tags": {"genres": ["rock"]}},
                    }
                ]
            )

        exists_mock.assert_called_once_with("123", client=fake_admin_client)
        self.assertEqual(add_mock.call_count, 1)

        inserted_song = add_mock.call_args.args[0]
        self.assertEqual(inserted_song.title, "Imported")
        self.assertEqual(inserted_song.artist, "Importer")
        self.assertEqual(inserted_song.genre, "rock")
        self.assertEqual(inserted_song.speed, 2)
        self.assertEqual(add_mock.call_args.kwargs, {"client": fake_admin_client})
        self.assertEqual(stats["inserted"], 1)


if __name__ == "__main__":
    unittest.main()