"""Procesador LLM LOCAL via Ollama (gratis, sin API key, sin costo).

Alternativa a ClaudeProcessor: misma interfaz (duck-typing), pero habla con un
modelo local servido por Ollama en http://localhost:11434. Read-only para
mercados: SOLO enriquece texto (resume noticias, explica setups, interpreta
preguntas libres). NO toca ninguna decision de trading.

Soft-fail completo (igual filosofia que ClaudeProcessor):
- Si enable_ollama_integration=False -> todos los metodos retornan None.
- Si Ollama no esta corriendo / no responde -> None (el bot sigue igual).
- Si la respuesta es invalida -> None.

Cero dependencias nuevas: usa `requests` (ya en requirements). El usuario debe
tener Ollama instalado y un modelo bajado (`ollama pull <modelo>`).
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

import requests

from app.config.settings import Settings

logger = logging.getLogger(__name__)

# Cada cuanto re-chequear que Ollama esta vivo (evita pingear en cada llamada).
_REACHABLE_CACHE_SECONDS = 60.0


class OllamaProcessor:
    def __init__(self, settings: Settings, repository: Any = None) -> None:
        self.settings = settings
        self.repository = repository
        self._calls_this_cycle = 0
        self._cache: dict[str, tuple[float, str]] = {}
        self._reachable_until = 0.0
        self._reachable = False

    # -- paridad de interfaz con ClaudeProcessor --------------------------- #
    def reset_cycle(self) -> None:
        self._calls_this_cycle = 0

    def estimated_cost_today(self) -> float:
        return 0.0  # Ollama es local y gratis

    def _base_url(self) -> str:
        return str(getattr(self.settings, "ollama_base_url", "http://localhost:11434")).rstrip("/")

    def _ping(self) -> bool:
        """Chequea (con cache) que el servidor Ollama responde."""
        now = time.time()
        if now < self._reachable_until:
            return self._reachable
        try:
            resp = requests.get(f"{self._base_url()}/api/tags", timeout=2)
            self._reachable = resp.status_code == 200
        except requests.RequestException:
            self._reachable = False
        if not self._reachable:
            logger.warning(
                "Ollama no responde en %s (LLM local desactivado este rato)",
                self._base_url(),
            )
        self._reachable_until = now + _REACHABLE_CACHE_SECONDS
        return self._reachable

    def is_available(self) -> bool:
        if not getattr(self.settings, "enable_ollama_integration", False):
            return False
        return self._ping()

    def _call(
        self, system: str, user: str, max_tokens: int | None = None
    ) -> str | None:
        cap = int(getattr(self.settings, "ollama_calls_per_cycle_cap", 6))
        if self._calls_this_cycle >= cap:
            return None
        if not self.is_available():
            return None

        cache_key = hashlib.sha256((system + user).encode("utf-8")).hexdigest()
        cached = self._cache.get(cache_key)
        if cached:
            expiry, val = cached
            if time.time() < expiry:
                return val

        num_predict = int(max_tokens or getattr(self.settings, "ollama_max_tokens", 256))
        payload = {
            "model": str(getattr(self.settings, "ollama_model", "llama3.1")),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"num_predict": num_predict, "temperature": 0.2},
        }
        timeout = int(getattr(self.settings, "ollama_timeout_seconds", 30))
        try:
            resp = requests.post(
                f"{self._base_url()}/api/chat", json=payload, timeout=timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            logger.warning("Ollama call failed; devuelvo None (soft-fail)")
            return None

        text = (data.get("message") or {}).get("content")
        if not text or not isinstance(text, str):
            return None
        text = text.strip()

        ttl = float(getattr(self.settings, "ollama_cache_ttl_seconds", 3600))
        self._cache[cache_key] = (time.time() + ttl, text)
        self._calls_this_cycle += 1
        return text

    def generate(
        self, system: str, user: str, max_tokens: int | None = None
    ) -> str | None:
        """Primitiva PUBLICA de generacion de texto (soft-fail), reusada por la capa
        asesora (TradingReasoner). Devuelve None si Ollama esta off/caido/invalido o
        si se excedio el cap del ciclo. Hereda throttle + cache + reachability de
        `_call`. No toca ninguna decision de trading: solo texto."""
        return self._call(system, user, max_tokens=max_tokens)

    # -- mismos prompts que ClaudeProcessor (duck-typing) ------------------ #
    def summarize_news(self, news_items: list[dict], symbol: str) -> str | None:
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
        user = f"Comandos disponibles: {commands_str}\n\nPregunta del usuario:\n{text}"
        return self._call(system, user, max_tokens=200)


def build_llm_processor(settings: Settings, repository: Any = None) -> Any:
    """Factory del proveedor LLM (todos soft-fail, opt-in, read-only):

      - enable_ollama_integration=True  -> OllamaProcessor (local, gratis)
      - en otro caso                    -> ClaudeProcessor (API, soft-fail si off)

    Ambos exponen la misma interfaz, asi que el resto del bot no cambia. Si los dos
    estan off, el ClaudeProcessor simplemente retorna None en todo (sin LLM).
    Ollama tiene prioridad si esta habilitado.
    """
    if getattr(settings, "enable_ollama_integration", False):
        return OllamaProcessor(settings, repository)
    from app.intelligence.claude_processor import ClaudeProcessor

    return ClaudeProcessor(settings, repository)
