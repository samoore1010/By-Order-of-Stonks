"""Kalshi public data should remain usable even if private auth fails."""
import asyncio
import httpx
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from backend.providers import Kalshi


def test_public_market_data_unsigned_private_account_signed(monkeypatch):
    key = ed25519.Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    monkeypatch.setenv("KALSHI_API_KEY_ID", "test-key")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY_PEM", pem)
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path.endswith("/markets"):
            assert "kalshi-access-key" not in request.headers
            assert "kalshi-access-signature" not in request.headers
            return httpx.Response(200, json={"markets": [{"ticker": "TEST"}]})
        if request.url.path.endswith("/portfolio/balance"):
            assert request.headers["kalshi-access-key"] == "test-key"
            assert request.headers.get("kalshi-access-signature")
            return httpx.Response(401, json={"error": "invalid key"})
        raise AssertionError("Unexpected route")

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs:
                        original(transport=httpx.MockTransport(handler), **kwargs))
    result = asyncio.run(Kalshi().diagnostics())
    assert result["public_markets"]["ok"] is True
    assert result["public_markets"]["returned_markets"] == 1
    assert result["private_account"]["ok"] is False
    assert "401" in result["private_account"]["error"]
    assert len(seen) == 2


def test_public_data_does_not_require_keys(monkeypatch):
    monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY_PEM", raising=False)
    def handler(request):
        assert "kalshi-access-key" not in request.headers
        return httpx.Response(200, json={"markets": []})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs:
                        original(transport=httpx.MockTransport(handler), **kwargs))
    result = asyncio.run(Kalshi().diagnostics())
    assert result["public_markets"]["ok"] is True
    assert result["private_account"]["status"] == "not_configured"
