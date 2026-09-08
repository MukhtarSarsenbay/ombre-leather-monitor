import asyncio
import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from app.config import Settings
from app.scraper import PriceReadError, parse_monamie_api, read_monamie_api


@pytest.fixture
def offers():
    return json.loads(Path(__file__).with_name("fixtures").joinpath("monamie-offers.json").read_text())


def test_verified_sku_and_price(offers):
    assert parse_monamie_api(offers, Settings(_env_file=None)).price_kzt == 74800
    assert parse_monamie_api(offers, Settings(_env_file=None, expected_volume_ml=100)).price_kzt == 104880


@pytest.mark.parametrize("change", ["size", "currency", "zero", "missing", "error"])
def test_rejects_unverified_offer(offers, change):
    offer = offers["data"]["offers"]["size"]["73559"]
    if change == "size":
        offer["capacity"]["NAME"] = "100"
    elif change == "currency":
        offer["priceFormatted"] = "74 800 ₽"
    elif change == "zero":
        offer["priceFormatted"] = "0 тг."
    elif change == "missing":
        del offers["data"]["offers"]["size"]["73559"]
    else:
        offers["status"] = "error"
    with pytest.raises(PriceReadError):
        parse_monamie_api(offers, Settings(_env_file=None))


def test_anonymous_csrf_handshake_preserves_cookie(monkeypatch, offers):
    calls = []
    csrf = "a" * 32
    def handle(request):
        calls.append(request)
        data = parse_qs(request.content.decode())
        assert data["productId"] == ["74160"]
        if len(calls) == 1:
            return httpx.Response(200, headers={"Set-Cookie": "session=anonymous; Path=/"}, json={
                "status": "error", "errors": [{"code": "invalid_csrf", "customData": {"csrf": csrf}}],
            })
        assert data["sessid"] == [csrf]
        assert "session=anonymous" in request.headers["cookie"]
        return httpx.Response(200, json=deepcopy(offers))
    client_type = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client_type(transport=httpx.MockTransport(handle), **kw))
    result = asyncio.run(read_monamie_api(Settings(_env_file=None)))
    assert result.price_kzt == 74800 and len(calls) == 2


def test_api_failure_falls_back_to_browser(monkeypatch):
    from unittest.mock import AsyncMock
    from app.scraper import read_monamie_quote
    monkeypatch.setattr("app.scraper.read_monamie_api", AsyncMock(side_effect=PriceReadError("API blocked")))
    browser = AsyncMock(return_value="verified browser result")
    monkeypatch.setattr("app.scraper.read_monamie_browser", browser)
    assert asyncio.run(read_monamie_quote(Settings(_env_file=None))) == "verified browser result"
    browser.assert_awaited_once()
