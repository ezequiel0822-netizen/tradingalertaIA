import logging

import requests

from app.config.settings import Settings


logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, settings: Settings) -> None:
        self.bot_token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id
        self.timeout = settings.request_timeout_seconds

    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_message(self, text: str, chat_id: str | None = None) -> bool:
        if not self.enabled():
            logger.warning("Telegram not configured: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": chat_id or self.chat_id, "text": text}

        try:
            response = requests.post(url, data=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Telegram send failed without exposing secrets: %s", exc)
            return False

        if not data.get("ok"):
            logger.warning("Telegram did not confirm delivery")
            return False

        return True
