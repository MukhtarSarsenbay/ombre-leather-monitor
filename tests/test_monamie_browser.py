"""Offline DOM regression test using an actual captured product fragment.

Opt in with RUN_BROWSER_TESTS=1 after installing Playwright Chromium.
"""
import asyncio
import os
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from app.config import Settings
from app.scraper import PriceReadError, extract_monamie_quote


@pytest.mark.skipif(os.getenv("RUN_BROWSER_TESTS") != "1", reason="opt-in browser test")
def test_captured_monamie_dom():
    async def check():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.route("**/*", lambda route: route.abort())
                await page.set_content(Path(__file__).with_name("fixtures").joinpath("monamie-product.html").read_text())
                settings = Settings(_env_file=None)
                result = await extract_monamie_quote(page, settings)
                assert result.price_kzt == 74800 and result.volume_ml == 50
                # A UI update between size and price updates must fail closed.
                await page.locator('.js-product-detail__price-now').evaluate(
                    "node => node.textContent = '69 000 тг.'"
                )
                with pytest.raises(PriceReadError):
                    await extract_monamie_quote(page, settings)
            finally:
                await browser.close()
    asyncio.run(check())
