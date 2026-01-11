from __future__ import annotations

import os
from dotenv import load_dotenv
from supabase import create_client

# โหลด env ให้ชัวร์
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError("SUPABASE_URL or SUPABASE_SERVICE_KEY not set")

# Singleton-style client
supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_KEY,
)
