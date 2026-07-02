import logging
from typing import Any

import requests

from app.alerts.telegram_notifier import TelegramNotifier
from app.assistant.command_handler import BasicTelegramAssistant
from app.config.settings import Settings
from app.database.repository import Repository


logger = logging.getLogger(__name__)


class TelegramAssistantPoller:
    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        notifier: TelegramNotifier,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.notifier = notifier
        self.handler = BasicTelegramAssistant(settings, repository)

    def enabled(self) -> bool:
        return (
            self.settings.enable_telegram_assistant
            and bool(self.settings.telegram_bot_token)
            and bool(self.settings.telegram_chat_id)
        )

    def process_updates(self) -> int:
        if not self.enabled():
            return 0

        updates = self._get_updates()
        handled = 0
        last_update_id: int | None = None
        try:
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    last_update_id = update_id

                message = update.get("message") or update.get("edited_message") or {}
                chat = message.get("chat") or {}
                chat_id = str(chat.get("id") or "")
                text = str(message.get("text") or "").strip()
                if not text:
                    continue

                if chat_id != str(self.settings.telegram_chat_id):
                    logger.info("Ignoring Telegram message from unauthorized chat")
                    continue

                # v3.9.4: un comando que crashea NO envenena el bot. Antes, una
                # excepcion aca impedia persistir el offset -> Telegram re-entregaba
                # el MISMO update cada ciclo y el bot quedaba muerto/sordo hasta que
                # el update expirara (~24h), con posiciones abiertas sin gestionar.
                try:
                    reply = self.handler.handle(text)
                except Exception:
                    logger.exception("Telegram command crashed; el bot sigue vivo")
                    reply = (
                        "Ese comando fallo internamente; el bot sigue vivo. "
                        "Proba de nuevo o con otros argumentos."
                    )
                if self.notifier.send_message(reply, chat_id=chat_id):
                    handled += 1
        finally:
            # El offset SIEMPRE avanza sobre lo ya leido (aun si algo lanza arriba):
            # un update problematico se procesa a lo sumo una vez.
            if last_update_id is not None:
                self.repository.set_state("telegram_last_update_id", str(last_update_id))

        return handled

    def _get_updates(self) -> list[dict[str, Any]]:
        token = self.settings.telegram_bot_token
        if not token:
            return []

        last_seen = self.repository.get_state("telegram_last_update_id")
        offset = int(last_seen) + 1 if last_seen and last_seen.isdigit() else None
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        params: dict[str, Any] = {
            "timeout": 0,
            "limit": self.settings.telegram_assistant_max_updates,
            "allowed_updates": ["message", "edited_message"],
        }
        if offset is not None:
            params["offset"] = offset

        try:
            response = requests.get(
                url,
                params=params,
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Telegram assistant polling failed without exposing secrets: %s", exc)
            return []

        if not payload.get("ok"):
            logger.warning("Telegram assistant polling was not confirmed by Telegram")
            return []

        result = payload.get("result") or []
        return [item for item in result if isinstance(item, dict)]
