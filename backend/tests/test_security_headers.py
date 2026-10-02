"""The interface is never indexed (2026-09-21).

The staging link is shared publicly for user testing, so every response — the SPA
shell, the API, the probes — carries `X-Robots-Tag: noindex, nofollow`, and the
built interface ships a `robots.txt` that disallows everything. Together they keep a
public UAT URL out of search results without putting a second gate in front of it.
"""
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_every_response_refuses_indexing():
    for path in ("/healthz", "/livez", "/readyz", "/v1/meta/version"):
        r = client.get(path)
        assert r.headers.get("x-robots-tag") == "noindex, nofollow", path


def test_the_interface_ships_a_robots_file_that_disallows_everything():
    robots = REPO_ROOT / "frontend" / "public" / "robots.txt"
    assert robots.is_file(), "frontend/public/robots.txt is copied into the built interface"
    text = robots.read_text()
    assert "User-agent: *" in text and "Disallow: /" in text
