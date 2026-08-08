import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_client_module(fake_supabase_root: Path):
    module_path = PROJECT_ROOT / "supabase_client" / "client.py"
    sys.path.insert(0, str(fake_supabase_root))
    try:
        spec = importlib.util.spec_from_file_location("zwift_supabase_client", module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


class SupabaseClientTest(unittest.TestCase):
    def test_raises_when_env_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_supabase = Path(temp_dir) / "supabase"
            fake_supabase.mkdir()
            (fake_supabase / "__init__.py").write_text("def create_client(url, key):\n    return object()\n")

            with unittest.mock.patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(RuntimeError):
                    load_client_module(Path(temp_dir))

    def test_create_client_with_environment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_supabase = Path(temp_dir) / "supabase"
            fake_supabase.mkdir()
            (fake_supabase / "__init__.py").write_text(
                "def create_client(url, key):\n"
                "    return ('created', url, key)\n"
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "SUPABASE_URL": "https://example.supabase.co",
                    "SUPABASE_PUBLISHABLE_KEY": "testkey",
                },
                clear=True,
            ):
                module = load_client_module(Path(temp_dir))

            self.assertEqual(module.supabase, ("created", "https://example.supabase.co", "testkey"))

    def test_songs_table_query_chain(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_supabase = Path(temp_dir) / "supabase"
            fake_supabase.mkdir()
            (fake_supabase / "__init__.py").write_text(
                "class Query:\n"
                "    def __init__(self):\n"
                "        self.calls = []\n"
                "    def select(self, arg):\n"
                "        self.calls.append(('select', arg))\n"
                "        return self\n"
                "    def limit(self, arg):\n"
                "        self.calls.append(('limit', arg))\n"
                "        return self\n"
                "    def execute(self):\n"
                "        return {'data': [{'id': 1}], 'status_code': 200}\n"
                "def create_client(url, key):\n"
                "    class Client:\n"
                "        def table(self, name):\n"
                "            self.name = name\n"
                "            return Query()\n"
                "    return Client()\n"
            )

            with unittest.mock.patch.dict(
                os.environ,
                {
                    "SUPABASE_URL": "https://example.supabase.co",
                    "SUPABASE_PUBLISHABLE_KEY": "testkey",
                },
                clear=True,
            ):
                module = load_client_module(Path(temp_dir))

            result = module.supabase.table("songs").select("*").limit(1).execute()
            self.assertEqual(result["status_code"], 200)
            self.assertEqual(result["data"][0]["id"], 1)

    @unittest.skipUnless(
        os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_PUBLISHABLE_KEY"),
        "Supabase credentials not configured",
    )
    def test_integration_songs_table(self):
        module = load_client_module(Path("."))
        response = module.supabase.table("songs").select("*").limit(1).execute()
        self.assertIn("data", response)
        self.assertIsInstance(response["data"], list)


if __name__ == "__main__":
    unittest.main()