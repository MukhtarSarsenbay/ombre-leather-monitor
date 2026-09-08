"""Manual CI diagnosis with a public product URL and no notification secrets."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.scraper import PriceReadError, read_monamie_api, read_monamie_browser


async def main():
    settings = Settings(_env_file=None, browser_channel="chrome", browser_timeout_ms=45000)
    try:
        quote = await read_monamie_api(settings)
    except PriceReadError as exc:
        print(json.dumps({"api_ok": False, "error": str(exc)}, ensure_ascii=False), flush=True)
    else:
        print(quote.model_dump_json(indent=2))
        return 0
    try:
        quote = await read_monamie_browser(settings)
    except PriceReadError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(quote.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
