# filepath: tests/test_parser_upload.py
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

from workout.parser import parse_and_save_zwo_file, parse_zwo_string

SIMPLE_ZWO = """<?xml version="1.0" encoding="UTF-8"?>
<Workout Name="Short" Author="Me" SportType="1">
  <Warmup Duration="60" Power="100"/>
</Workout>
"""

class ParserUploadTest(unittest.TestCase):
    @patch("workout.parser.supabase")
    def test_parse_and_upload_single_workout(self, fake_supabase):
        # arrange: fake supabase.table(...).insert(...).execute()
        table_mock = MagicMock()
        insert_mock = MagicMock()
        exec_mock = MagicMock()
        exec_mock.execute.return_value = {"data": []}
        # support chaining: supabase.table(...).insert(...).execute()
        fake_supabase.table.return_value = table_mock
        table_mock.insert.return_value = insert_mock
        insert_mock.execute.return_value = {"data": []}

        # create temp zwo file
        with tempfile.NamedTemporaryFile(suffix=".zwo", delete=False, mode="w", encoding="utf-8") as tf:
            tf.write(SIMPLE_ZWO)
            tf_path = Path(tf.name)

        try:
            out_path = parse_and_save_zwo_file(tf_path, target_dir=tf_path.parent)
            # file saved
            self.assertTrue(out_path.exists())
            parsed = json.loads(out_path.read_text(encoding="utf-8"))
            # ensure upload was attempted
            fake_supabase.table.assert_called_with("workouts")
            # check that insert was called with a record
            called_record = table_mock.insert.call_args.args[0]
            self.assertIn("name", called_record)
            self.assertIn("parsed_workout", called_record)
            self.assertEqual(called_record["author"], "Me")
            # sport_type_is_bike should be True because SportType="1"
            self.assertTrue(called_record["sport_type_is_bike"])
        finally:
            try:
                tf_path.unlink()
            except Exception:
                pass
            try:
                out_path.unlink()
            except Exception:
                pass

if __name__ == "__main__":
    unittest.main()
