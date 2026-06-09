"""v2.11.0 — TradingReasoner: capa LLM ASESORA (local, gratis, read-only).

Construye sobre `OllamaProcessor` (transporte LLM local: throttle + cache + soft-fail)
y agrega prompts del dominio trading. Su unico output es TEXTO en lenguaje natural:

  - assess_market()  -> lectura honesta del mercado del dia (insumo de /market)
  - analyze_loss()   -> post-mortem de un trade perdedor (insumo de ContinuousLearner)
  - explain_setup()  -> explica un setup en lenguaje claro (enriquece una alerta)

PRINCIPIO INAMOVIBLE (igual que el resto del proyecto): el LLM **NO decide ni ejecuta
trades**. Esta clase, a proposito, NO tiene ningun metodo que devuelva una decision,
un bool de ejecutar, ni una probabilidad que alimente el gate. Todos los metodos
devuelven `str | None`. Si el advisor esta apagado, Ollama no corre, o la respuesta
es invalida -> `None`, y el bot sigue EXACTAMENTE igual.

Opt-in: `enable_llm_advisor` (default False) ademas de `enable_ollama_integration`
(que controla el transporte). Cero dependencias nuevas (reusa `requests` via Ollama).
"""

from __future__ import annotations

import logging
from typing import Any

from app.config.settings import Settings

logger = logging.getLogger(__name__)


def _g(data: dict[str, Any], key: str, default: str = "N/A") -> Any:
    """Lectura defensiva: nunca aplica format specs numericos (evita crashear si el
    valor es 'N/A'/None). Devuelve el valor crudo o un default legible."""
    value = data.get(key)
    if value is None or value == "":
        return default
    return value


class TradingReasoner:
    """Asesor LLM local. Solo genera texto; jamas toma ni habilita decisiones."""

    def __init__(self, settings: Settings, processor: Any | None = None) -> None:
        self.settings = settings
        # `processor` inyectable para tests; en runtime se crea un OllamaProcessor.
        self._processor = processor

    # -- plumbing soft-fail ------------------------------------------------ #
    def _enabled(self) -> bool:
        return bool(getattr(self.settings, "enable_llm_advisor", False))

    def _processor_or_none(self) -> Any | None:
        if self._processor is None:
            try:
                from app.intelligence.ollama_processor import OllamaProcessor

                self._processor = OllamaProcessor(self.settings)
            except Exception:  # pragma: no cover - defensivo
                logger.warning("TradingReasoner: no se pudo crear el processor LLM")
                return None
        return self._processor

    def _generate(self, system: str, user: str, max_tokens: int | None = None) -> str | None:
        if not self._enabled():
            return None
        proc = self._processor_or_none()
        if proc is None:
            return None
        gen = getattr(proc, "generate", None)
        if not callable(gen):
            return None
        try:
            text = gen(system, user, max_tokens=max_tokens)
        except Exception:
            logger.warning("TradingReasoner: generacion fallo; soft-fail -> None")
            return None
        if not isinstance(text, str) or not text.strip():
            return None
        return text.strip()

    # -- capacidades asesoras (todas devuelven texto o None) --------------- #
    def assess_market(self, macro: dict[str, Any]) -> str | None:
        """Evaluacion honesta del mercado de HOY. NO da senales de compra/venta."""
        system = (
            "Eres un analista de trading prudente. Resumes el estado del mercado del "
            "dia en 3-5 oraciones, en espanol, claro y honesto. Indicas el nivel de "
            "cautela sugerido (bajo/medio/alto) y que evitar hoy. NO des senales de "
            "compra/venta de ningun activo ni numeros de entrada/SL/TP."
        )
        user = (
            "Contexto de hoy:\n"
            f"- Sesion: {_g(macro, 'session')}\n"
            f"- VIX: {_g(macro, 'vix')} (normal <20, alto >25)\n"
            f"- DXY: {_g(macro, 'dxy')}\n"
            f"- Win rate ultimos 30d: {_g(macro, 'wr_30d')}\n"
            f"- Drawdown acumulado: {_g(macro, 'dd_cumulative')}\n"
            f"- Eventos economicos: {_g(macro, 'events', 'ninguno')}\n\n"
            "Evaluacion del dia:"
        )
        return self._generate(system, user, max_tokens=300)

    def analyze_loss(self, trade: dict[str, Any]) -> str | None:
        """Post-mortem honesto de un trade perdedor: mal setup vs mala suerte."""
        system = (
            "Eres un coach de trading honesto. Explicas en 3-4 oraciones, en espanol, "
            "por que un trade pudo perder y que leccion deja, sin excusas y sin "
            "recomendaciones de compra/venta. Distingue entre 'mal setup' y 'mala "
            "suerte' (varianza)."
        )
        user = (
            "Trade perdedor:\n"
            f"- Simbolo: {_g(trade, 'symbol')}\n"
            f"- Direccion: {_g(trade, 'direction')}\n"
            f"- Estrategia: {_g(trade, 'strategy_name')}\n"
            f"- Entrada: {_g(trade, 'entry_price')}\n"
            f"- Stop: {_g(trade, 'stop_loss')}\n"
            f"- Resultado R: {_g(trade, 'r_multiple')}\n"
            f"- Sesion: {_g(trade, 'session')}\n"
            f"- RSI al entry: {_g(trade, 'rsi_entry')}\n"
            f"- ATR%: {_g(trade, 'atr_value')}\n"
            f"- Razon de cierre: {_g(trade, 'close_reason')}\n\n"
            "Que salio mal y que leccion deja:"
        )
        return self._generate(system, user, max_tokens=300)

    def analyze_win(self, trade: dict[str, Any]) -> str | None:
        """Post-mortem honesto de un trade ganador: edge repetible vs varianza.

        Insumo del ContinuousLearner (Fase C). Igual que analyze_loss, solo TEXTO:
        no da senales ni decisiones. Pide al modelo que sea esceptico de atribuir el
        resultado a habilidad cuando pudo ser suerte."""
        system = (
            "Eres un coach de trading honesto. Explicas en 3-4 oraciones, en espanol, "
            "por que un trade pudo ganar y que leccion REPETIBLE deja, sin euforia y "
            "sin recomendaciones de compra/venta. Distingue entre 'buen setup "
            "repetible' y 'suerte' (varianza); se esceptico de atribuir todo a "
            "habilidad cuando la muestra es chica."
        )
        user = (
            "Trade ganador:\n"
            f"- Simbolo: {_g(trade, 'symbol')}\n"
            f"- Direccion: {_g(trade, 'direction')}\n"
            f"- Estrategia: {_g(trade, 'strategy_name')}\n"
            f"- Entrada: {_g(trade, 'entry_price')}\n"
            f"- Stop: {_g(trade, 'stop_loss')}\n"
            f"- Resultado R: {_g(trade, 'r_multiple')}\n"
            f"- Sesion: {_g(trade, 'session')}\n"
            f"- RSI al entry: {_g(trade, 'rsi_entry')}\n"
            f"- ATR%: {_g(trade, 'atr_value')}\n"
            f"- Razon de cierre: {_g(trade, 'close_reason')}\n\n"
            "Por que gano y que leccion repetible deja:"
        )
        return self._generate(system, user, max_tokens=300)

    def explain_setup(self, context: dict[str, Any]) -> str | None:
        """Explica un setup en lenguaje natural. Es EXPLICACION, no recomendacion."""
        system = (
            "Eres un analista que EXPLICA por que un setup tecnico luce interesante, "
            "en 2-3 oraciones en espanol, didactico. Es una explicacion, NO una "
            "recomendacion: no digas 'compra'/'vende' ni des entrada/SL/TP."
        )
        user = (
            "Setup:\n"
            f"- Simbolo: {_g(context, 'symbol')}\n"
            f"- Estrategia: {_g(context, 'strategy_name')}\n"
            f"- Direccion: {_g(context, 'direction')}\n"
            f"- RSI: {_g(context, 'rsi')}\n"
            f"- MACD: {_g(context, 'macd_state')}\n"
            f"- ATR%: {_g(context, 'atr')}\n"
            f"- Sesion: {_g(context, 'session')}\n"
            f"- Prob. ML de win: {_g(context, 'prob_win')}\n\n"
            "Explicacion breve del setup:"
        )
        return self._generate(system, user, max_tokens=200)

    def daily_summary(self, stats: dict[str, Any]) -> str | None:
        """Lectura del dia + UNA leccion para manana (texto). NO da senales."""
        system = (
            "Eres un coach de trading honesto. Te dan el resultado del dia. Escribe "
            "2-3 oraciones en espanol: una lectura honesta del dia y UNA leccion "
            "accionable para manana. Sin recomendaciones de compra/venta de activos."
        )
        user = (
            "Resultado de hoy:\n"
            f"- Trades cerrados: {_g(stats, 'total')}\n"
            f"- Ganados: {_g(stats, 'wins')} | Perdidos: {_g(stats, 'losses')}\n"
            f"- R neto del dia: {_g(stats, 'net_r')}\n\n"
            "Lectura del dia + 1 leccion para manana:"
        )
        return self._generate(system, user, max_tokens=250)
