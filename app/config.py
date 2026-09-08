from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    product_url: str = "https://goldapple.kz/26375200001-ombre-leather"
    monamie_url: str = "https://www.monamie.kz/catalog/dlya_muzhchin/muzhskie_aromaty/tom_ford_ombr_leather_parfyumirovannaya_voda_id74160/"
    expected_volume_ml: int = Field(default=50, gt=0)
    threshold_kzt: int = Field(default=71000, gt=0)
    notification_channel: Literal["telegram", "email"] = "telegram"
    telegram_bot_token: SecretStr = SecretStr("")
    telegram_chat_id: str = ""
    api_token: SecretStr = SecretStr("")
    browser_channel: str = ""
    monamie_headless: bool = False
    browser_timeout_ms: int = Field(default=60000, ge=1000, le=120000)
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    email_from: str = ""
    email_to: str = ""

    @field_validator("product_url")
    @classmethod
    def validate_product_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.netloc != "goldapple.kz":
            raise ValueError("PRODUCT_URL must be an HTTPS goldapple.kz URL")
        return value

    def require_notifications(self) -> None:
        if self.notification_channel == "telegram":
            if not self.telegram_bot_token.get_secret_value() or not self.telegram_chat_id:
                raise ValueError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        elif not all((self.smtp_host, self.smtp_username,
                      self.smtp_password.get_secret_value(), self.email_from, self.email_to)):
            raise ValueError("Set SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, EMAIL_FROM and EMAIL_TO")
