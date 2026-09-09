import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.config import Settings
from app.notify import NotificationError, send_notification
from app.scraper import PriceReadError, Quote, read_monamie_quote, read_quote


class CheckResult(BaseModel):
    quote: Quote
    threshold_kzt: int
    below_threshold: bool
    notified: bool
    dry_run: bool


class CheckReport(BaseModel):
    results: list[CheckResult]
    errors: dict[str, str]
    checked_at: datetime

    @property
    def ok(self) -> bool:
        return not self.errors


def alert_text(quote: Quote, threshold: int) -> str:
    money = lambda n: f"{n:,}".replace(",", " ")
    checked = quote.checked_at.astimezone(ZoneInfo("Asia/Almaty"))
    return (
        f"{quote.store}: {quote.product}\n"
        f"{money(quote.price_kzt)} ₸ — {quote.price_type}\n"
        f"Ниже вашего порога {money(threshold)} ₸.\n"
        f"Проверено: {checked:%d.%m.%Y %H:%M} (Алматы)\n"
        f"Наличие и итоговую цену проверьте на сайте.\n{quote.url}"
    )


class Monitor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.lock = asyncio.Lock()
        self.last_result: CheckReport | None = None
        self.last_error: str | None = None
        self.last_attempt_at: datetime | None = None

    async def check(self, dry_run: bool = False) -> CheckReport:
        async with self.lock:
            self.last_attempt_at = datetime.now(timezone.utc)
            if not dry_run:
                self.settings.require_notifications()
            results, errors = [], {}
            readers = (("goldapple", "Gold Apple", read_quote),
                       ("monamie", "Mon Amie", read_monamie_quote))
            for key, store, reader in readers:
                if self.settings.check_store not in ("all", key):
                    continue
                try:
                    for attempt in range(2):
                        try:
                            quote = await reader(self.settings)
                            break
                        except PriceReadError:
                            if attempt:
                                raise
                            await asyncio.sleep(3)
                    below = quote.price_kzt < self.settings.threshold_kzt
                    result = CheckResult(quote=quote, threshold_kzt=self.settings.threshold_kzt,
                                         below_threshold=below, notified=False, dry_run=dry_run)
                    results.append(result)
                    if below and not dry_run:
                        await send_notification(self.settings, alert_text(quote, self.settings.threshold_kzt))
                        result.notified = True
                except (PriceReadError, NotificationError) as exc:
                    errors[store] = str(exc)
            if errors and not dry_run:
                # One operational notice per run; healthy-store alerts still go out.
                try:
                    await send_notification(
                        self.settings,
                        "Не удалось завершить проверку Ombré Leather:\n"
                        + "\n".join(f"{store}: {error}" for store, error in errors.items())
                        + "\nЭто не уведомление о снижении цены.",
                    )
                except NotificationError:
                    errors["notification"] = "Failure notification also failed"
            report = CheckReport(results=results, errors=errors, checked_at=self.last_attempt_at)
            self.last_result = report
            self.last_error = "; ".join(errors.values()) or None
            return report
