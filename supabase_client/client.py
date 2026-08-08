from __future__ import annotations

import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_PUBLISHABLE_KEY")

if not supabase_url:
    raise RuntimeError("SUPABASE_URL is not set")

if not supabase_key:
    raise RuntimeError("SUPABASE_PUBLISHABLE_KEY is not set")

supabase = create_client(supabase_url, supabase_key)