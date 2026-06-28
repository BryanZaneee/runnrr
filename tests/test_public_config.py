"""GET /api/public-config — browser-safe Supabase bootstrap."""
from __future__ import annotations

from backend import config


class TestPublicConfig:
    def test_returns_supabase_keys_from_config(self, client, monkeypatch):
        c, _ = client
        monkeypatch.setattr(config, "SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.setattr(config, "SUPABASE_ANON_KEY", "anon-test-key")
        r = c.get("/api/public-config")
        assert r.status_code == 200
        body = r.json()
        assert body == {
            "supabase_url": "https://example.supabase.co",
            "supabase_anon_key": "anon-test-key",
        }
