# app/main.py
from __future__ import annotations

from app.bootstrap import create_app
from app.lifecycle import register_lifecycle

app = create_app()
register_lifecycle(app)
