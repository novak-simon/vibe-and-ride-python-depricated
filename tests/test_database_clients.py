import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def load_module(module_name: str, module_path: Path, env: dict, fake_supabase: MagicMock):
    original_supabase = sys.modules.pop("supabase", None)
    original_module = sys.modules.pop(module_name, None)
    with patch.dict(os.environ, env, clear=True), patch("dotenv.load_dotenv", return_value=True):
        sys.modules["supabase"] = fake_supabase
        try:
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            module = importlib.util.module_from_spec(spec)
            assert spec.loader
            spec.loader.exec_module(module)
            return module
        finally:
            sys.modules.pop("supabase", None)
            if original_supabase is not None:
                sys.modules["supabase"] = original_supabase
            if original_module is not None:
                sys.modules[module_name] = original_module


class DatabaseClientTest(unittest.TestCase):
    def test_public_client_uses_publishable_key(self):
        fake_supabase = MagicMock()
        fake_supabase.create_client = MagicMock(return_value="public-client")

        module = load_module(
            "database.client",
            PROJECT_ROOT / "database" / "client.py",
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_PUBLISHABLE_KEY": "publickey",
            },
            fake_supabase,
        )

        self.assertEqual(module.supabase, "public-client")
        fake_supabase.create_client.assert_called_once_with(
            "https://example.supabase.co", "publickey"
        )

    def test_public_client_falls_back_to_next_public_env(self):
        fake_supabase = MagicMock()
        fake_supabase.create_client = MagicMock(return_value="public-client")

        module = load_module(
            "database.client",
            PROJECT_ROOT / "database" / "client.py",
            {
                "NEXT_PUBLIC_SUPABASE_URL": "https://example.supabase.co",
                "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY": "publickey",
            },
            fake_supabase,
        )

        self.assertEqual(module.supabase, "public-client")
        fake_supabase.create_client.assert_called_once_with(
            "https://example.supabase.co", "publickey"
        )

    def test_admin_client_uses_secret_key(self):
        fake_supabase = MagicMock()
        fake_supabase.create_client = MagicMock(return_value="admin-client")

        module = load_module(
            "database.admin_client",
            PROJECT_ROOT / "database" / "admin_client.py",
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_SECRET_KEY": "secretkey",
            },
            fake_supabase,
        )

        self.assertEqual(module.get_admin_supabase(), "admin-client")
        fake_supabase.create_client.assert_called_once_with(
            "https://example.supabase.co", "secretkey"
        )

    def test_admin_client_requires_secret_key(self):
        fake_supabase = MagicMock()
        fake_supabase.create_client = MagicMock(return_value="admin-client")

        module = load_module(
            "database.admin_client",
            PROJECT_ROOT / "database" / "admin_client.py",
            {"SUPABASE_URL": "https://example.supabase.co"},
            fake_supabase,
        )

        with self.assertRaises(RuntimeError) as exc:
            module.get_admin_supabase()
        self.assertIn("SUPABASE_SECRET_KEY is not configured", str(exc.exception))

    def test_normal_application_does_not_require_secret_key(self):
        fake_supabase = MagicMock()
        fake_supabase.create_client = MagicMock(return_value="public-client")

        module = load_module(
            "database.client",
            PROJECT_ROOT / "database" / "client.py",
            {
                "SUPABASE_URL": "https://example.supabase.co",
                "SUPABASE_PUBLISHABLE_KEY": "publickey",
            },
            fake_supabase,
        )

        self.assertEqual(module.supabase, "public-client")
