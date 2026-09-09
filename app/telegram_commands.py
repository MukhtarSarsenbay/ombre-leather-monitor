"""Process private Telegram commands in finite, scheduled GitHub jobs.

Only acknowledge a price request after delivering its result or failure notice.
No raw messages, usernames, or bot credentials are written to job logs/state.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path

import httpx

from app.config import Settings
from app.notify import NotificationError, send_notification


WELCOME = (
    "Нажмите /check или отправьте эту команду — пришлю текущую цену Gold Apple сюда в чат, "
    "даже если она выше 71 000 ₸.\n"
    "Новые запросы проверяются раз в 5 минут; ответ может занять дольше при задержках сервиса.\n"
    "Автоматические проверки: 09:00 и 19:00 (Алматы), уведомление при цене ниже 71 000 ₸."
)


async def telegram_call(settings: Settings, method: str, payload: dict):
    token = settings.telegram_bot_token.get_secret_value()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"https://api.telegram.org/bot{token}/{method}", json=payload)
        data = response.json()
        if response.status_code != 200 or not isinstance(data, dict) or data.get("ok") is not True:
            raise NotificationError(f"Telegram {method} failed")
        return data.get("result")
    except (httpx.HTTPError, ValueError):
        raise NotificationError(f"Telegram {method} unavailable") from None


def requested_command(update: dict, chat_id: str) -> str | None:
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat, sender = message.get("chat", {}), message.get("from", {})
    if (chat.get("type") != "private" or str(chat.get("id")) != chat_id
            or str(sender.get("id")) != chat_id or sender.get("is_bot", False)):
        return None
    text = message.get("text")
    if not isinstance(text, str):
        return None
    command = text.strip().split(maxsplit=1)[0] if text.strip() else ""
    # Commands addressed to this deployed bot are also accepted in its private chat.
    command = command.removesuffix("@ombre_leather_bot")
    return command if command in ("/check", "/start") else None


async def acknowledge(settings: Settings, offset: int):
    # The returned update (if any) remains unconfirmed for the next run.
    await telegram_call(settings, "getUpdates", {
        "offset": offset, "limit": 1, "timeout": 0, "allowed_updates": ["message"],
    })


async def probe(settings: Settings, state_path: Path) -> bool:
    updates = await telegram_call(settings, "getUpdates", {
        "limit": 100, "timeout": 0, "allowed_updates": ["message"],
    })
    if not isinstance(updates, list) or any(
        not isinstance(u, dict) or type(u.get("update_id")) is not int for u in updates
    ):
        raise NotificationError("Telegram returned invalid updates")
    commands = [requested_command(u, settings.telegram_chat_id) for u in updates]
    requested = "/check" in commands
    offset = max((u["update_id"] for u in updates), default=-1) + 1
    if "/start" in commands and not requested:
        await send_notification(settings, WELCOME)
    state_path.write_text(json.dumps({"offset": offset, "requested": requested}))
    if updates and not requested:
        await acknowledge(settings, offset)
    return requested


async def run_requested(settings: Settings, state_path: Path) -> bool:
    from app.monitor import Monitor

    state = json.loads(state_path.read_text())
    if state.get("requested") is not True:
        return True
    settings = settings.model_copy(update={"check_store": "goldapple", "notification_channel": "telegram"})
    await send_notification(settings, "Запрос принят. Проверяю текущую цену Gold Apple…")
    report = await Monitor(settings).check(notify_current=True)
    delivered = (bool(report.results) and all(r.notified for r in report.results))
    # A scrape failure is handled too if the monitor delivered its failure notice.
    handled_failure = bool(report.errors) and "notification" not in report.errors
    if delivered or handled_failure:
        await acknowledge(settings, state["offset"])
    print(report.model_dump_json(indent=2))
    return report.ok


async def configure(settings: Settings):
    info = await telegram_call(settings, "getWebhookInfo", {})
    if not isinstance(info, dict) or info.get("url"):
        raise NotificationError("An existing webhook must be reviewed before enabling polling")
    await telegram_call(settings, "setMyCommands", {
        "commands": [{"command": "check", "description": "Проверить текущую цену Gold Apple"}],
        "scope": {"type": "chat", "chat_id": int(settings.telegram_chat_id)},
    })
    await telegram_call(settings, "setChatMenuButton", {
        "chat_id": int(settings.telegram_chat_id), "menu_button": {"type": "commands"},
    })
    await send_notification(settings, WELCOME)
    print("Telegram /check menu and keyboard configured.")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("probe", "run", "configure"))
    parser.add_argument("--state", type=Path, default=Path("data/telegram-command.json"))
    args = parser.parse_args()
    settings = Settings(notification_channel="telegram")
    try:
        settings.require_notifications()
        if args.action == "configure":
            await configure(settings)
        elif args.action == "probe":
            args.state.parent.mkdir(parents=True, exist_ok=True)
            requested = await probe(settings, args.state)
            if output := os.environ.get("GITHUB_OUTPUT"):
                with open(output, "a") as f:
                    f.write(f"requested={str(requested).lower()}\n")
            print(json.dumps({"price_requested": requested}))
        else:
            return 0 if await run_requested(settings, args.state) else 1
    except (NotificationError, ValueError):
        print("Telegram command processing failed; check configuration or retry the job.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
