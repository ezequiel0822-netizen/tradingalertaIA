"""v3.0.0 — Veto del ensemble LLM en el gate (Fase B p2 del roadmap v3.1).

DOS modelos locales (primario + segunda opinion) evaluan si hay una RED FLAG para
tomar un trade que las reglas YA aprobaron. Si CUALQUIERA marca red flag -> VETO
(el trade baja a paper-only, sin order_send a MT5).

SUBTRACTIVO por construccion: se invoca DESPUES de que reglas + promotion gate +
ML gate aprobaron, asi que SOLO puede bloquear, jamas habilitar. Soft-fail total:
si el flag esta off, no hay processor LLM, o algo falla/ambiguo -> NO veta (allow),
y el sistema se comporta EXACTAMENTE igual que sin esta capa.

No toca `mt5_demo_trader.py`. No produce ninguna senal positiva de ejecucion: el
unico output "fuerte" posible es un VETO. Resolucion conservadora del plan v3.0
(que tenia al LLM dando luz verde): aca el LLM solo puede frenar.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_RED_FLAG_SYSTEM = (
    "Eres un gestor de riesgo de trading EXTREMADAMENTE prudente. Te dan un trade "
    "que ya paso los filtros del sistema. Tu unica tarea: detectar RED FLAGS, es "
    "decir razones de peso para NO tomarlo (contexto adverso, riesgo/recompensa "
    "pobre, timing dudoso, sobrecompra/sobreventa extrema). Responde SOLO con una "
    "palabra: 'SI' si hay una red flag clara, 'NO' si no la hay. Ante la duda, 'NO'."
)


def _g(context: dict[str, Any], key: str, default: str = "N/A") -> Any:
    value = context.get(key)
    return default if value is None or value == "" else value


def _red_flag_user(context: dict[str, Any]) -> str:
    return (
        "Trade ya aprobado por las reglas:\n"
        f"- Simbolo: {_g(context, 'symbol')}\n"
        f"- Direccion: {_g(context, 'direction')}\n"
        f"- Estrategia: {_g(context, 'strategy_name')}\n"
        f"- Entrada: {_g(context, 'entry')}\n"
        f"- Stop: {_g(context, 'stop')}\n"
        f"- Take profit: {_g(context, 'tp')}\n"
        f"- Sesion: {_g(context, 'session')}\n"
        f"- RSI al entry: {_g(context, 'rsi')}\n"
        f"- ATR%: {_g(context, 'atr')}\n"
        f"- VIX: {_g(context, 'vix')}\n\n"
        "Hay una RED FLAG clara para NO tomar este trade? Responde SI o NO."
    )


def _says_red_flag(text: str | None) -> bool:
    """True solo si la respuesta empieza claramente por SI. Ambiguo/None/NO -> False
    (soft-fail = NO veta)."""
    if not text or not isinstance(text, str):
        return False
    t = text.strip().lower().lstrip("\"'*-. ")
    return t.startswith(("si", "sí", "yes"))


def ensemble_veto(
    settings: Any, context: dict[str, Any], processor: Any | None
) -> tuple[bool, str]:
    """Devuelve (veto, reason). veto=True -> el trade debe bajar a paper-only.

    Soft-fail (siempre hacia NO-veto, identico a no tener la capa):
      - enable_llm_ensemble=False            -> (False, ...)
      - processor sin .generate (no Ollama)  -> (False, ...)
      - todos los modelos fallan/ambiguos    -> (False, ...)
    Cada modelo se evalua aislado: el error de uno no descarta el flag del otro.
    """
    if not getattr(settings, "enable_llm_ensemble", False):
        return False, "ensemble off"
    gen = getattr(processor, "generate", None)
    if not callable(gen):
        return False, "sin processor LLM (soft-fail)"

    primary = str(getattr(settings, "ollama_model", "llama3.1") or "")
    second = str(getattr(settings, "ollama_second_model", "mistral") or "")
    system = _RED_FLAG_SYSTEM
    user = _red_flag_user(context)

    flagged: list[str] = []
    seen: set[str] = set()
    for name in (primary, second):
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            resp = gen(system, user, max_tokens=8, model=name)
        except Exception:
            logger.warning("ensemble_veto: modelo %s fallo; ignorado (soft-fail)", name)
            continue
        if _says_red_flag(resp):
            flagged.append(name)

    if flagged:
        return True, f"red flag por: {', '.join(flagged)}"
    return False, "sin red flags"
