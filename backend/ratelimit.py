"""Shared slowapi limiter.

Lives in its own module because both app.py and builder.py need the instance
at import time, and app.py imports builder — importing it from app.py would be
circular.
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.config import RATE_LIMIT_ENABLED

limiter = Limiter(key_func=get_remote_address, enabled=RATE_LIMIT_ENABLED)
