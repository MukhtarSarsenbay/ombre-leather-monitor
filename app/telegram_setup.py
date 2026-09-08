"""Read /start updates to identify your chat; never sends a message."""
import asyncio

import httpx

from app.config import Settings


async def main() -> int:
    token = Settings().telegram_bot_token.get_secret_value()
    if not token:
        print("Set TELEGRAM_BOT_TOKEN in .env first.")
        return 1
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"https://api.telegram.org/bot{token}/getUpdates")
        data = response.json()
        if response.status_code != 200 or not data.get("ok"):
            print("Telegram rejected getUpdates. Check the token and any existing webhook.")
            return 1
    except (httpx.HTTPError, ValueError):
        print("Could not contact Telegram.")
        return 1
    chats = set()
    for update in data.get("result", []):
        message = update.get("message", {})
        chat = message.get("chat", {})
        if chat.get("type") == "private" and message.get("text", "").split(" ")[0] == "/start":
            chats.add(chat["id"])
    if len(chats) != 1:
        print("Expected one private /start chat. Send /start to your new bot and try again.")
        return 1
    print(f"TELEGRAM_CHAT_ID={chats.pop()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
