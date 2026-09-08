"""Try a public storefront using an ephemeral browser through the local proxy."""
import asyncio
import json
import sys
from pathlib import Path

from playwright.async_api import Error, async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.scraper import extract_monamie_quote


async def main():
    settings = Settings(_env_file=None)
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            proxy={"server": "http://127.0.0.1:40000"},
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        try:
            page = await browser.new_page(
                locale="ru-RU", timezone_id="Asia/Almaty",
                viewport={"width": 1440, "height": 1000},
            )
            page.set_default_timeout(60000)
            response = await page.goto(settings.monamie_url, wait_until="domcontentloaded")
            print(json.dumps({"http_status": response.status if response else None}), flush=True)
            try:
                await page.locator("h1.product-detail__head-title").wait_for(state="visible")
                await page.locator(".js-product-detail__price-now").wait_for(state="visible")
                await asyncio.sleep(2)
                if page.url.rstrip("/") != settings.monamie_url.rstrip("/"):
                    raise RuntimeError("Unexpected product redirect")
                quote = await extract_monamie_quote(page, settings)
                print(quote.model_dump_json(indent=2))
                return 0
            except Error:
                print(json.dumps({"ok": False, "title": (await page.title())[:120]}))
                return 1
        finally:
            await browser.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
