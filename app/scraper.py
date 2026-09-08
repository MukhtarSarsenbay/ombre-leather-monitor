import asyncio
import json
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlsplit

from playwright.async_api import Error as BrowserError, async_playwright
from pydantic import BaseModel

from app.config import Settings


class PriceReadError(RuntimeError):
    pass


class Quote(BaseModel):
    store: str = "Gold Apple"
    product: str
    volume_ml: int
    price_kzt: int
    price_type: str = "по максимальной карте"
    url: str
    checked_at: datetime


def parse_card_price(text: str) -> int:
    """Accept only a KZT amount immediately preceding the maximum-card label."""
    text = " ".join(unicodedata.normalize("NFKC", text).split()).lower()
    matches = re.findall(
        r"(?<![\d.,])(?P<price>\d{1,3}(?: \d{3})+|\d+)\s*₸\s*по максимальной карте",
        text,
    )
    if len(matches) != 1:
        raise PriceReadError("Maximum-card price is missing or ambiguous")
    price = int(matches[0].replace(" ", ""))
    if price <= 0:
        raise PriceReadError("Maximum-card price must be positive")
    return price


def validate_product(title: str, selected_volume: str, expected_volume: int) -> None:
    normalized = unicodedata.normalize("NFKD", title.casefold())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    volumes = re.findall(r"\b(\d+)\s*мл\b", normalized)
    if "tom ford" not in normalized or "ombre leather" not in normalized:
        raise PriceReadError("Unexpected product title")
    if volumes != [str(expected_volume)] or selected_volume != str(expected_volume):
        raise PriceReadError("Bottle size does not match EXPECTED_VOLUME_ML")


async def read_quote(settings: Settings) -> Quote:
    # Selectors verified against the live 50 ml product on 2026-09-08.
    # No fallback to generic prices, recommendations, or search snippets.
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(
                headless=True, channel=settings.browser_channel or None,
            )
            try:
                page = await browser.new_page(
                    locale="ru-KZ", timezone_id="Asia/Almaty",
                    viewport={"width": 1440, "height": 1000},
                )
                page.set_default_timeout(settings.browser_timeout_ms)
                await page.goto(settings.product_url, wait_until="domcontentloaded")
                row = page.locator('[data-test-id="bestLoyalty"]:visible')
                await row.wait_for(state="visible")
                # Allow the client-rendered price and variant to settle.
                await asyncio.sleep(2)
                actual = urlsplit(page.url)
                expected = urlsplit(settings.product_url)
                if (actual.scheme, actual.netloc, actual.path.rstrip("/")) != (
                    expected.scheme, expected.netloc, expected.path.rstrip("/")
                ):
                    raise PriceReadError("Product page redirected to another URL")
                title = await page.locator('h1[itemprop="name"]:visible').inner_text()
                selected = page.locator('input[name="units"]:checked')
                volume = await selected.input_value()
                validate_product(title, volume, settings.expected_volume_ml)
                price = parse_card_price(await row.inner_text())
                return Quote(product=title, volume_ml=int(volume), price_kzt=price,
                             url=settings.product_url, checked_at=datetime.now(timezone.utc))
            finally:
                await browser.close()
        except BrowserError:
            # Browser exceptions may contain page data; keep API/log errors controlled.
            raise PriceReadError(
                "Could not read Gold Apple: browser unavailable, page blocked, or layout changed"
            ) from None


def parse_monamie_offer(
    title: str, volume: str, price_info: dict, displayed_price: str,
    expected_volume: int, url: str,
) -> Quote:
    """Validate the selected size's sale price against the visible current price.

    Mon Amie's JSON-LD contains the old base price, so it is not a price source.
    Selectors and data-info fields verified on the live page on 2026-09-08.
    """
    product = f"{title.strip()} {volume.strip()} мл"
    validate_product(product, volume.strip(), expected_volume)
    amount = price_info.get("price")
    if type(amount) is not int or amount <= 0:
        raise PriceReadError("Mon Amie: invalid selected-variant price")
    for value in (displayed_price, price_info.get("priceFormatted", "")):
        normalized = " ".join(unicodedata.normalize("NFKC", str(value)).split())
        match = re.fullmatch(r"(\d{1,3}(?: \d{3})+|\d+) (?:тг\.|₸)", normalized)
        if match is None or int(match[1].replace(" ", "")) != amount:
            raise PriceReadError("Mon Amie: displayed KZT price does not match the selected variant")
    return Quote(store="Mon Amie", product=product, volume_ml=expected_volume,
                 price_kzt=amount, price_type="цена на сайте", url=url,
                 checked_at=datetime.now(timezone.utc))


async def extract_monamie_quote(page, settings: Settings) -> Quote:
    # Read all fields in one DOM snapshot so an asynchronous size/price update
    # cannot mix two variants. Scope to the product, excluding recommendations.
    fields = await page.locator(".product-detail__top").evaluate("""root => {
        const one = selector => {
            const nodes = root.querySelectorAll(selector);
            if (nodes.length !== 1) throw new Error('Missing or ambiguous product field');
            return nodes[0];
        };
        const selected = one('input[name="capacity"]:checked').closest('label[data-info]');
        if (!selected) throw new Error('Missing selected variant');
        const currentPrice = one('.js-product-detail__price-now').cloneNode(true);
        currentPrice.querySelectorAll('.was-pr-item').forEach(node => node.remove());
        return {
            title: one('.product-detail__head-brand').textContent.trim() + ' ' +
                   one('h1.product-detail__head-title').textContent.trim(),
            volume: selected.querySelector('.product-detail-prop__item-inner').textContent.trim(),
            priceInfo: selected.getAttribute('data-info'),
            displayedPrice: currentPrice.textContent.trim()
        };
    }""")
    try:
        info = json.loads(fields["priceInfo"])
    except (TypeError, ValueError):
        raise PriceReadError("Mon Amie: invalid variant price data") from None
    if not isinstance(info, dict):
        raise PriceReadError("Mon Amie: invalid variant price data")
    return parse_monamie_offer(fields["title"], fields["volume"], info,
                               fields["displayedPrice"], settings.expected_volume_ml,
                               settings.monamie_url)


async def read_monamie_quote(settings: Settings) -> Quote:
    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(
                headless=settings.monamie_headless,
                channel=settings.browser_channel or None,
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
            )
            try:
                page = await browser.new_page(
                    locale="ru-RU", timezone_id="Asia/Almaty",
                    viewport={"width": 1440, "height": 1000},
                )
                page.set_default_timeout(settings.browser_timeout_ms)
                await page.goto(settings.monamie_url, wait_until="domcontentloaded")
                # The security page also has an h1. Wait for the actual product
                # instead, allowing automatic browser verification to finish.
                await page.locator("h1.product-detail__head-title").wait_for(state="visible")
                await page.locator('.js-product-detail__price-now').wait_for(state="visible")
                await asyncio.sleep(2)
                actual, expected = urlsplit(page.url), urlsplit(settings.monamie_url)
                if (actual.scheme, actual.netloc, actual.path.rstrip("/")) != (
                    expected.scheme, expected.netloc, expected.path.rstrip("/")
                ):
                    raise PriceReadError("Mon Amie: redirected away from the product")
                return await extract_monamie_quote(page, settings)
            finally:
                await browser.close()
        except BrowserError:
            raise PriceReadError(
                "Mon Amie: browser unavailable, security check did not finish, or layout changed"
            ) from None
