from __future__ import annotations

import importlib
import os
import sys

from dotenv import load_dotenv

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_PUBLISHABLE_KEY")

if not supabase_url:
    raise RuntimeError("SUPABASE_URL is not set")

if not supabase_key:
    raise RuntimeError("SUPABASE_PUBLISHABLE_KEY is not set")


def _load_create_client():
    importlib.invalidate_caches()
    sys.modules.pop("supabase", None)
    supabase_module = importlib.import_module("supabase")
    return getattr(supabase_module, "create_client")


create_client = _load_create_client()
supabase = create_client(supabase_url, supabase_key)