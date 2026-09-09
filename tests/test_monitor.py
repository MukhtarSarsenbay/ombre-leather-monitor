import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.monitor import Monitor
from app.notify import NotificationError, send_notification
from app.scraper import PriceReadError, Quote, parse_card_price, parse_monamie_offer, validate_product


def settings(**kwargs):
    kwargs.setdefault("check_store", "all")
    return Settings(_env_file=None, **kwargs)


def quote(price=84150, store="Gold Apple"):
    return Quote(store=store, product="Tom Ford Ombré Leather 50 мл", volume_ml=50,
                 price_kzt=price, url="https://goldapple.kz/26375200001-ombre-leather",
                 checked_at=datetime.now(timezone.utc))


@pytest.mark.parametrize("text,expected", [
    ("93 500 ₸\n84 150 ₸\nпо максимальной карте", 84150),
    ("70\u00a0999 ₸ по максимальной карте", 70999),
    ("71\u202f000 ₸ по максимальной карте", 71000),
])
def test_card_price_uses_label_not_regular_price(text, expected):
    assert parse_card_price(text) == expected


@pytest.mark.parametrize("text", [
    "69999 ₸", "0 ₸ по максимальной карте", "69 000 ₽ по максимальной карте",
    "70,999.99 ₸ по максимальной карте", "Just a moment…",
    "69 000 ₸ по максимальной карте 68 000 ₸ по максимальной карте",
])
def test_missing_or_ambiguous_prices_fail(text):
    with pytest.raises(PriceReadError):
        parse_card_price(text)


def test_exact_product_and_size():
    validate_product("Tom Ford Парфюмерная вода Ombré Leather 50 мл", "50", 50)
    for title, selected in [("Tom Ford Ombré Leather 100 мл", "100"),
                            ("Tom Ford Ombré Leather 50 мл", "100"),
                            ("Tom Ford Oud Wood 50 мл", "50")]:
        with pytest.raises(PriceReadError):
            validate_product(title, selected, 50)


def test_monamie_reads_discount_not_base_price():
    info = {"price": 74800, "priceFormatted": "74 800 тг.", "basePrice": 93500}
    result = parse_monamie_offer("TOM FORD Ombré Leather", "50", info,
                                 "74 800 тг.", 50, "https://www.monamie.kz/")
    assert result.price_kzt == 74800


@pytest.mark.parametrize("volume,amount,displayed", [
    ("100", 74800, "74 800 тг."),
    ("50", 74800, "93 500 тг."),
    ("50", 74800, "74 800 ₽"),
    ("50", 74800, "93 500 тг.74 800 тг."),
    ("50", 0, "0 тг."),
    ("50", 69000.5, "69 000 тг."),
])
def test_monamie_rejects_mismatched_variant_or_price(volume, amount, displayed):
    with pytest.raises(PriceReadError):
        parse_monamie_offer("TOM FORD Ombré Leather", volume,
                            {"price": amount, "priceFormatted": displayed}, displayed,
                            50, "https://www.monamie.kz/")


@pytest.mark.parametrize("price,alert", [(70999, True), (71000, False), (84150, False)])
def test_threshold_is_strict_and_checks_both_stores(monkeypatch, price, alert):
    monkeypatch.setattr("app.monitor.read_quote", AsyncMock(return_value=quote(price)))
    monamie = AsyncMock(return_value=quote(90000, "Mon Amie"))
    monkeypatch.setattr("app.monitor.read_monamie_quote", monamie)
    send = AsyncMock()
    monkeypatch.setattr("app.monitor.send_notification", send)
    result = asyncio.run(Monitor(settings(telegram_bot_token="test", telegram_chat_id="123")).check())
    assert result.ok
    assert len(result.results) == 2
    assert result.results[0].notified is alert
    assert send.await_count == int(alert)
    monamie.assert_awaited_once()


def test_dry_run_never_sends(monkeypatch):
    monkeypatch.setattr("app.monitor.read_quote", AsyncMock(return_value=quote(69000)))
    monkeypatch.setattr("app.monitor.read_monamie_quote", AsyncMock(return_value=quote(68000, "Mon Amie")))
    send = AsyncMock()
    monkeypatch.setattr("app.monitor.send_notification", send)
    result = asyncio.run(Monitor(settings()).check(dry_run=True))
    assert result.ok and all(r.below_threshold and not r.notified for r in result.results)
    send.assert_not_awaited()


@pytest.mark.parametrize("selected,expected", [("goldapple", "Gold Apple"), ("monamie", "Mon Amie")])
def test_split_schedule_checks_and_alerts_only_selected_store(monkeypatch, selected, expected):
    gold = AsyncMock(return_value=quote(69000))
    monamie = AsyncMock(return_value=quote(68000, "Mon Amie"))
    send = AsyncMock()
    monkeypatch.setattr("app.monitor.read_quote", gold)
    monkeypatch.setattr("app.monitor.read_monamie_quote", monamie)
    monkeypatch.setattr("app.monitor.send_notification", send)
    result = asyncio.run(Monitor(settings(check_store=selected, telegram_bot_token="test",
                                         telegram_chat_id="123")).check())
    assert result.ok and len(result.results) == 1
    assert result.results[0].quote.store == expected
    assert result.results[0].notified
    assert gold.await_count == int(selected == "goldapple")
    assert monamie.await_count == int(selected == "monamie")
    send.assert_awaited_once()


@pytest.mark.parametrize("price", [70999, 71000, 84150])
def test_requested_check_always_reports_real_price_once(monkeypatch, price):
    monkeypatch.setattr("app.monitor.read_quote", AsyncMock(return_value=quote(price)))
    send = AsyncMock()
    monkeypatch.setattr("app.monitor.send_notification", send)
    result = asyncio.run(Monitor(settings(check_store="goldapple", telegram_bot_token="test",
                                         telegram_chat_id="123")).check(notify_current=True))
    assert result.ok and result.results[0].notified
    assert result.results[0].below_threshold is (price < 71000)
    send.assert_awaited_once()
    message = send.await_args.args[1]
    assert "Проверка по вашему запросу" in message
    assert f"{price:,}".replace(",", " ") in message
    assert ("Цена пока не ниже" in message) is (price >= 71000)


def test_requested_check_dry_run_never_sends(monkeypatch):
    monkeypatch.setattr("app.monitor.read_quote", AsyncMock(return_value=quote(69000)))
    send = AsyncMock()
    monkeypatch.setattr("app.monitor.send_notification", send)
    result = asyncio.run(Monitor(settings(check_store="goldapple")).check(
        dry_run=True, notify_current=True))
    assert result.ok and not result.results[0].notified
    send.assert_not_awaited()


def test_store_failure_does_not_prevent_other_store_alert(monkeypatch):
    monkeypatch.setattr("app.monitor.read_quote", AsyncMock(side_effect=PriceReadError("blocked")))
    monkeypatch.setattr("app.monitor.read_monamie_quote", AsyncMock(return_value=quote(69000, "Mon Amie")))
    monkeypatch.setattr("app.monitor.asyncio.sleep", AsyncMock())
    send = AsyncMock()
    monkeypatch.setattr("app.monitor.send_notification", send)
    result = asyncio.run(Monitor(settings(telegram_bot_token="test", telegram_chat_id="123")).check())
    assert not result.ok and result.errors == {"Gold Apple": "blocked"}
    assert result.results[0].notified
    assert "Mon Amie" in send.await_args_list[0].args[1]
    assert send.await_count == 2  # Discount plus operational failure notice.


def test_delivery_failure_is_not_marked_notified(monkeypatch):
    monkeypatch.setattr("app.monitor.read_quote", AsyncMock(return_value=quote(69000)))
    monkeypatch.setattr("app.monitor.read_monamie_quote", AsyncMock(return_value=quote(90000, "Mon Amie")))
    monkeypatch.setattr("app.monitor.send_notification", AsyncMock(side_effect=NotificationError("delivery failed")))
    result = asyncio.run(Monitor(settings(telegram_bot_token="test", telegram_chat_id="123")).check())
    assert not result.ok and not result.results[0].notified
    assert "notification" in result.errors


def test_api_auth_and_partial_failure_status(monkeypatch):
    app = create_app(settings(api_token="test-api-token"))
    monkeypatch.setattr("app.monitor.read_quote", AsyncMock(return_value=quote()))
    monkeypatch.setattr("app.monitor.read_monamie_quote", AsyncMock(side_effect=PriceReadError("blocked")))
    monkeypatch.setattr("app.monitor.asyncio.sleep", AsyncMock())
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.post("/check").status_code == 401
        assert client.get("/status", headers={"Authorization": "Bearer wrong"}).status_code == 401
        headers = {"Authorization": "Bearer test-api-token"}
        response = client.post("/check?dry_run=true", headers=headers)
        assert response.status_code == 502
        assert response.json()["results"][0]["quote"]["price_kzt"] == 84150
        assert client.get("/status", headers=headers).json()["last_error"] == "blocked"


def test_unconfigured_api_is_closed():
    with TestClient(create_app(settings())) as client:
        assert client.post("/check").status_code == 503


def test_telegram_error_does_not_expose_token(monkeypatch):
    secret = "123:very-secret"
    async def fail(*args, **kwargs):
        raise httpx.ConnectError(f"https://api.telegram.org/bot{secret}/sendMessage")
    monkeypatch.setattr(httpx.AsyncClient, "post", fail)
    with pytest.raises(NotificationError) as caught:
        asyncio.run(send_notification(settings(telegram_bot_token=secret, telegram_chat_id="1"), "test"))
    assert secret not in str(caught.value)
