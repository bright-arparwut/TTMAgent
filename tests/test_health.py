"""Tests for /health and the lifespan pre-warm (app/main.py).

The preflight (app/preflight.py) trusts /health's embedding field, so these
lock in its contract: "cold" until the model is constructed, "ready" after,
and the lifespan builds it at boot only when EMBEDDING_PREWARM is on.
"""

import warnings
from types import SimpleNamespace

# Same harness noise as tests/line/test_webhook.py -- silence before import.
warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated",
)

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.config import Settings  # noqa: E402


class _FakeGetEmbeddings:
    """Stands in for the lru_cache-wrapped get_embeddings: callable, with
    cache_info reporting whether the model has been constructed."""

    def __init__(self):
        self.warmup_texts: list[str] = []
        self.built = False

    def __call__(self):
        self.built = True
        return SimpleNamespace(embed_query=self.warmup_texts.append)

    def cache_info(self):
        return SimpleNamespace(currsize=1 if self.built else 0)


def _settings(prewarm: bool) -> Settings:
    return Settings(
        line_channel_secret="secret",
        line_channel_access_token="token",
        embedding_prewarm=prewarm,
    )


def test_prewarm_on_builds_model_at_boot_and_health_reports_ready(monkeypatch):
    fake = _FakeGetEmbeddings()
    monkeypatch.setattr(main, "get_embeddings", fake)
    monkeypatch.setattr(main, "get_settings", lambda: _settings(prewarm=True))

    with TestClient(main.app) as client:
        assert fake.warmup_texts  # model loaded during lifespan, not on a request
        body = client.get("/health").json()
    assert body == {"status": "ok", "embedding": "ready"}


def test_prewarm_off_keeps_lazy_load_and_health_reports_cold(monkeypatch):
    fake = _FakeGetEmbeddings()
    monkeypatch.setattr(main, "get_embeddings", fake)
    monkeypatch.setattr(main, "get_settings", lambda: _settings(prewarm=False))

    with TestClient(main.app) as client:
        assert not fake.warmup_texts
        body = client.get("/health").json()
    assert body == {"status": "ok", "embedding": "cold"}
