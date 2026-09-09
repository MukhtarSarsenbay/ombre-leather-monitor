import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import Settings
from app.monitor import CheckReport, CheckResult
from app.notify import NotificationError, send_notification
from app.scraper import Quote
from app.telegram_commands import probe, requested_command, run_requested, telegram_call


def settings():
    return Settings(_env_file=None, telegram_bot_token="secret-test", telegram_chat_id="123")


def update(text="/check", uid=1, chat_id=123, sender_id=123, chat_type="private"):
    return {"update_id": uid, "message": {"chat": {"id": chat_id, "type": chat_type},
            "from": {"id": sender_id, "is_bot": False}, "text": text}}


@pytest.mark.parametrize("payload,expected", [
    (update(), "/check"), (update("/check@ombre_leather_bot"), "/check"),
    (update("/start"), "/start"), (update("/check@another_bot"), None),
    (update(chat_id=999), None), (update(sender_id=999), None),
    (update(chat_type="group"), None), (update("hi"), None),
    ({"update_id": 1, "edited_message": update()["message"]}, None),
])
def test_private_owner_commands_only(payload, expected):
    assert requested_command(payload, "123") == expected


def test_probe_coalesces_requests_and_keeps_them_pending(monkeypatch, tmp_path):
    call = AsyncMock(return_value=[update(uid=5), update(uid=6)])
    monkeypatch.setattr("app.telegram_commands.telegram_call", call)
    state = tmp_path / "state.json"
    assert asyncio.run(probe(settings(), state)) is True
    call.assert_awaited_once()  # No offset confirmation before the price reply.
    assert json.loads(state.read_text()) == {"offset": 7, "requested": True}
    assert "123" not in state.read_text()


def test_probe_confirms_unauthorized_messages_without_reply(monkeypatch, tmp_path):
    call = AsyncMock(side_effect=[[update(uid=5, sender_id=999)], []])
    send = AsyncMock()
    monkeypatch.setattr("app.telegram_commands.telegram_call", call)
    monkeypatch.setattr("app.telegram_commands.send_notification", send)
    assert asyncio.run(probe(settings(), tmp_path / "state.json")) is False
    assert call.await_args_list[1].args[2]["offset"] == 6
    send.assert_not_awaited()


def test_start_sends_menu_without_price_check(monkeypatch, tmp_path):
    call = AsyncMock(side_effect=[[update("/start")], []])
    send = AsyncMock()
    monkeypatch.setattr("app.telegram_commands.telegram_call", call)
    monkeypatch.setattr("app.telegram_commands.send_notification", send)
    assert asyncio.run(probe(settings(), tmp_path / "state.json")) is False
    send.assert_awaited_once()
    assert "/check" in send.await_args.args[1]


@pytest.mark.parametrize("delivered", [True, False])
def test_request_acknowledged_only_after_delivery(monkeypatch, tmp_path, delivered):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"offset": 7, "requested": True}))
    quote = Quote(product="Tom Ford Ombré Leather 50 мл", volume_ml=50, price_kzt=84150,
                  url="https://goldapple.kz/26375200001-ombre-leather", checked_at=datetime.now(timezone.utc))
    report = CheckReport(results=[CheckResult(quote=quote, threshold_kzt=71000,
                         below_threshold=False, notified=delivered, dry_run=False)],
                         errors={} if delivered else {"Gold Apple": "delivery failed", "notification": "failed"},
                         checked_at=quote.checked_at)
    check = AsyncMock(return_value=report)
    ack = AsyncMock()
    monkeypatch.setattr("app.monitor.Monitor.check", check)
    monkeypatch.setattr("app.telegram_commands.acknowledge", ack)
    monkeypatch.setattr("app.telegram_commands.send_notification", AsyncMock())
    assert asyncio.run(run_requested(settings(), state)) is delivered
    check.assert_awaited_once_with(notify_current=True)
    assert ack.await_count == int(delivered)


def test_telegram_transport_failure_redacts_bot_token(monkeypatch):
    monkeypatch.setattr(httpx.AsyncClient, "post", AsyncMock(side_effect=httpx.ConnectError(
        "https://api.telegram.org/botsecret-test/getUpdates")))
    with pytest.raises(NotificationError) as error:
        asyncio.run(telegram_call(settings(), "getUpdates", {}))
    assert "secret-test" not in str(error.value)


def test_notifications_include_native_check_keyboard(monkeypatch):
    post = AsyncMock(return_value=httpx.Response(200, json={"ok": True}))
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    asyncio.run(send_notification(settings(), "Current price"))
    markup = post.await_args.kwargs["json"]["reply_markup"]
    assert markup["keyboard"] == [[{"text": "/check"}]]
    assert markup["is_persistent"] is True
    assert "inline_keyboard" not in markup
