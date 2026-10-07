"""v3.14.1 — una sola fuente de precio por paper trade (forex/oro).

El bug (research/AGENTE_IA_V2_ADENDA_2026-10-07_oro.md): los paper trades de oro se
ABRÍAN con el precio del futuro de Yahoo (GC=F, ~$21 sobre el spot) y se MARCABAN con
el spot de MT5 (XAUUSD) → stops "tocados" al minuto con −3.5R/−5.1R que el mercado no
hizo, y ganancias falsas en los shorts. Con `PAPER_PRICE_FROM_MT5=true`:

- al abrir, los niveles de la señal se TRASLADAN al precio de MT5 de ese momento (ask
  para long, bid para short) conservando las distancias → `price_source='mt5'`;
- si MT5 no responde (o el desfase es absurdo: feed equivocado) quedan los niveles de
  Yahoo → `price_source='yahoo'`;
- cada trade se marca SOLO con su fuente (lifecycle / training_engine lo respetan).

`price_source` NULL = trade viejo (o flag apagado): comportamiento de siempre. Un trade
de ORO así es "oro mezclado" y su R no es del mercado.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from app.brokers.mt5_symbol_map import yahoo_to_mt5

logger = logging.getLogger(__name__)

PRICE_SOURCE_MT5 = "mt5"
PRICE_SOURCE_YAHOO = "yahoo"
# Más que esto entre Yahoo y MT5 no es una prima ni un spread: es otro instrumento o
# un feed roto (la prima del oro anduvo entre ~0.2 % y ~1.3 % en 2026).
MAX_REBASE_PCT = 3.0
REBASE_CATEGORIES = frozenset({"forex", "gold"})


@dataclass(frozen=True)
class EntryLevels:
    entry: float
    stop: float | None
    targets: tuple[float, ...]
    source: str              # 'mt5' | 'yahoo'
    source_entry: float      # entrada original de la señal (Yahoo)
    offset: float            # entry - source_entry (0.0 si no se trasladó)


def _num(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def rebase_levels(
    entry: float,
    stop: float | None,
    targets: list[float] | tuple[float, ...],
    mt5_price: float,
    max_pct: float = MAX_REBASE_PCT,
) -> EntryLevels | None:
    """Traslada entrada/stop/targets por (mt5_price − entry), conservando distancias.
    None si algún dato no sirve o el desfase supera `max_pct` % de la entrada."""
    e = _num(entry)
    p = _num(mt5_price)
    if e is None or p is None or e <= 0 or p <= 0:
        return None
    offset = p - e
    if abs(offset) / e * 100.0 > float(max_pct):
        return None
    s = _num(stop)
    new_targets: list[float] = []
    for t in targets or ():
        v = _num(t)
        if v is None:
            return None
        new_targets.append(v + offset)
    return EntryLevels(
        entry=p,
        stop=None if s is None else s + offset,
        targets=tuple(new_targets),
        source=PRICE_SOURCE_MT5,
        source_entry=e,
        offset=offset,
    )


def mt5_symbol_for(symbol: str, broker_profile: str = "icmarkets") -> str | None:
    return yahoo_to_mt5(str(symbol or ""), broker_profile)


def mt5_entry_price(
    mt5_reader, symbol: str, direction: str, broker_profile: str = "icmarkets"
) -> float | None:
    """Precio al que MT5 llenaría HOY la entrada: ask para long, bid para short.
    None si no hay reader, no está conectado, no hay mapeo o no hay tick."""
    if mt5_reader is None:
        return None
    mt5_symbol = mt5_symbol_for(symbol, broker_profile)
    if not mt5_symbol:
        return None
    try:
        if not mt5_reader.is_connected():
            return None
        tick = mt5_reader.get_tick(mt5_symbol)
    except Exception:
        return None
    if not tick:
        return None
    side = "bid" if str(direction or "long").lower() == "short" else "ask"
    value = _num(tick.get(side))
    return value if value is not None and value > 0 else None


def resolve_entry_levels(
    settings,
    mt5_reader,
    category: str,
    symbol: str,
    direction: str,
    entry: float,
    stop: float | None,
    targets: list[float] | tuple[float, ...],
) -> EntryLevels | None:
    """Niveles con los que se abre el paper trade.

    None = no aplica (flag apagado o categoría que no es forex/oro): se abre como
    siempre, sin `price_source`. Con el flag: MT5 si responde y el desfase es sano;
    si no, los niveles de Yahoo marcados 'yahoo'. Soft-fail: nunca lanza."""
    if not getattr(settings, "paper_price_from_mt5", False):
        return None
    if str(category or "").lower() not in REBASE_CATEGORIES:
        return None
    e = _num(entry)
    if e is None or e <= 0:
        return None
    try:
        price = mt5_entry_price(
            mt5_reader, symbol, direction,
            getattr(settings, "mt5_broker_profile", "icmarkets"),
        )
        if price is not None:
            levels = rebase_levels(e, stop, targets, price)
            if levels is not None:
                return levels
            logger.warning(
                "Precio MT5 de %s (%s) se aleja > %.1f%% de la señal (%s): "
                "el paper trade queda con precio de Yahoo",
                symbol, price, MAX_REBASE_PCT, e,
            )
    except Exception:
        logger.exception("Rebase a MT5 falló para %s; queda con precio de Yahoo", symbol)
    clean_targets = tuple(v for v in (_num(t) for t in targets or ()) if v is not None)
    return EntryLevels(
        entry=e,
        stop=_num(stop),
        targets=clean_targets,
        source=PRICE_SOURCE_YAHOO,
        source_entry=e,
        offset=0.0,
    )


def is_mixed_price_trade(trade: dict[str, Any] | None) -> bool:
    """Oro mezclado: paper trade de oro SIN fuente única (`price_source` NULL), abierto
    con el futuro de Yahoo y marcado con el spot de MT5. Su R no es del mercado."""
    if not trade:
        return False
    if str(trade.get("category") or "").lower() != "gold":
        return False
    # El scalping abre y marca con MT5 (símbolo MT5 directo): no mezcla fuentes.
    if int(trade.get("is_scalping") or 0) == 1:
        return False
    return not str(trade.get("price_source") or "").strip()


def without_mixed_gold(trades: list[dict[str, Any]], enabled: bool) -> list[dict[str, Any]]:
    """Filtra el oro mezclado si `enabled` (el flag); si no, devuelve la lista tal cual."""
    if not enabled:
        return trades
    return [t for t in trades if not is_mixed_price_trade(t)]
