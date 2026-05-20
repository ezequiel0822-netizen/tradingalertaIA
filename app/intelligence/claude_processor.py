"""Centralized Claude API processor.

Soft-fail completo:
- Si enable_claude_integration=False → todos los metodos retornan None.
- Si anthropic_api_key vacio → idem.
- Si import anthropic falla → idem.
- Si la API call falla → log warning, retorna None.

Caracteristicas:
- Throttle por ciclo (claude_calls_per_cycle_cap).
- Cache SHA256 sobre (system + user) prompts, TTL configurable.
- Telemetria de costo persistida en bot_state.
- Safety cap por dia (claude_max_cost_per_day_usd).

Read-only para mercados: solo razona, no ejecuta nada.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any

from app.config.settings import Settings


logger = logging.getLogger(__name__)


# Pricing aproximado Claude Haiku 4.5 (USD por millon de tokens)
# Si el usuario cambia claude_model, el cost es solo estimativo.
_HAIKU_INPUT_PER_M = 1.0
_HAIKU_OUTPUT_PER_M = 5.0


class ClaudeProcessor:
    def __init__(self, settings: Settings, repository: Any = None) -> None:
        self.settings = settings
        self.repository = repository
        self._client: Any = None
        self._calls_this_cycle = 0
        self._cache: dict[str, tuple[float, str]] = {}

    def reset_cycle(self) -> None:
        self._calls_this_cycle = 0

    def is_available(self) -> bool:
        if not self.settings.enable_claude_integration:
            return False
        if not self.settings.anthropic_api_key:
            return False
        return self._ensure_client()

    def _ensure_client(self) -> bool:
        if self._client is not None:
            return True
        try:
            from anthropic import Anthropic  # type: ignore[import-not-found]
        except ImportError:
            logger.warning(
                "anthropic package not installed; Claude integration disabled"
            )
            return False
        try:
            self._client = Anthropic(api_key=self.settings.anthropic_api_key)
            return True
        except Exception:
            logger.warning("Anthropic client init failed; Claude disabled")
            return False

    def _today_key(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _read_today_tokens(self) -> tuple[int, int]:
        if self.repository is None:
            return 0, 0
        date = self._today_key()
        try:
            i = int(self.repository.get_state(f"claude_input_tokens_{date}") or 0)
            o = int(self.repository.get_state(f"claude_output_tokens_{date}") or 0)
            return i, o
        except (ValueError, AttributeError):
            return 0, 0

    def _write_today_tokens(self, input_tokens: int, output_tokens: int) -> None:
        if self.repository is None:
            return
        date = self._today_key()
        i, o = self._read_today_tokens()
        try:
            self.repository.set_state(
                f"claude_input_tokens_{date}", str(i + input_tokens)
            )
            self.repository.set_state(
                f"claude_output_tokens_{date}", str(o + output_tokens)
            )
        except AttributeError:
            pass

    def estimated_cost_today(self) -> float:
        i, o = self._read_today_tokens()
        return (i / 1_000_000) * _HAIKU_INPUT_PER_M + (o / 1_000_000) * _HAIKU_OUTPUT_PER_M

    def _call(
        self, system: str, user: str, max_tokens: int | None = None
    ) -> str | None:
        if self._calls_this_cycle >= self.settings.claude_calls_per_cycle_cap:
            return None
        if not self.is_available():
            return None
        # Safety cap por dia
        if self.estimated_cost_today() >= self.settings.claude_max_cost_per_day_usd:
            logger.warning("Claude daily cost cap reached; skipping until UTC midnight")
            return None

        cache_key = hashlib.sha256((system + user).encode("utf-8")).hexdigest()
        cached = self._cache.get(cache_key)
        if cached:
            expiry, val = cached
            if time.time() < expiry:
                return val

        try:
            response = self._client.messages.create(
                model=self.settings.claude_model,
                max_tokens=max_tokens or self.settings.claude_max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception:
            logger.warning("Claude API call failed")
            return None

        try:
            text = response.content[0].text
        except (AttributeError, IndexError):
            return None

        # Token usage si disponible
        try:
            usage = response.usage
            self._write_today_tokens(
                int(getattr(usage, "input_tokens", 0)),
                int(getattr(usage, "output_tokens", 0)),
            )
        except Exception:
            pass

        self._cache[cache_key] = (
            time.time() + self.settings.claude_cache_ttl_seconds,
            text,
        )
        self._calls_this_cycle += 1
        return text

    def summarize_news(
        self, news_items: list[dict], symbol: str
    ) -> str | None:
        if not news_items:
            return None
        titles = [str(item.get("title") or "") for item in news_items[:5]]
        joined = "\n".join(f"- {t}" for t in titles if t)
        if not joined:
            return None
        system = (
            "Eres un asistente que sintetiza noticias financieras en 2-3 oraciones "
            "claras. Identifica si el conjunto es alcista, bajista o neutral para el "
            "activo. Sin recomendaciones de compra/venta. Responde en espanol."
        )
        user = f"Activo: {symbol}\nTitulares:\n{joined}\n\nSintesis:"
        return self._call(system, user, max_tokens=200)

    def expand_pro_analysis(self, pro: Any, snapshot: Any) -> str | None:
        if pro is None or snapshot is None:
            return None
        bias = getattr(pro, "bias", "")
        score = getattr(pro, "score", 0)
        setup = getattr(pro, "setup", "")
        symbol = getattr(snapshot, "symbol", "?")
        system = (
            "Eres un analista de trading que explica setups en 1-2 oraciones "
            "concretas. Sin recomendaciones de compra/venta. Responde en espanol."
        )
        user = (
            f"Activo: {symbol}\nSesgo: {bias}\nScore: {score}/100\nSetup: {setup}\n\n"
            f"Explicacion breve del setup:"
        )
        return self._call(system, user, max_tokens=150)

    def interpret_free_text(
        self, text: str, available_commands: list[str]
    ) -> str | None:
        if not text or len(text) > 500:
            return None
        commands_str = ", ".join(available_commands[:30])
        system = (
            "Eres un asistente de Telegram para un bot de trading. El usuario hace "
            "una pregunta libre. Si la pregunta mapea claramente a un comando, "
            "responde SOLO con el comando exacto (ej: '/pro NVDA'). Si no, "
            "responde con texto natural breve en espanol. Sin recomendaciones "
            "de compra/venta."
        )
        user = (
            f"Comandos disponibles: {commands_str}\n\nPregunta del usuario:\n{text}"
        )
        return self._call(system, user, max_tokens=200)
