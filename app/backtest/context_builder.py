"""Construye el StrategyContext del harness en la barra N (ESPEC §4, B1/B11).

Reusa los modulos REALES (analyze_ohlcv de technical_patterns) con ventanas que
TERMINAN en N: nada con indice > N entra en la decision. Es el corazon del
canario anti-look-ahead (§14): inyectar un spike en N+5 NO puede cambiar el
contexto en N, porque la ventana se corta en N+1.

Campos sin registro historico en v1 (news, pro, macro, learned_weights) van
None/empty: prohibido inventar valores historicos (B11). El completeness report
deja explicito que % del contexto quedo poblado, para que el reporte del run no
mienta sobre cuanta informacion tuvo realmente cada estrategia.

NO toca el ciclo vivo: ni importa mt5_demo_trader ni escribe en tablas vivas.
"""

from dataclasses import dataclass, fields

from app.analyzers.technical_patterns import analyze_ohlcv
from app.database.models import TokenSnapshot
from app.strategies.base import StrategyContext

# Profundidad de ventana para analyze_ohlcv: alcanza para todos los indicadores
# (SMA50, MACD>=35, Bollinger20, etc.) sin arrastrar miles de barras por bar.
DEFAULT_LOOKBACK = 250

# Campos que pueden faltar historia (B11). Se evaluan en el completeness report:
# 'poblado' significa que hubo dato real, no un default de relleno.
_COMPLETENESS_KEYS = ("price", "candles", "pattern", "pro", "news", "macro")


@dataclass(frozen=True)
class ContextCompleteness:
    """Cuanto del contexto quedo poblado con dato REAL en la barra N (B11)."""

    populated: int
    total: int
    pct: float
    missing: list[str]


def build_context(
    candles: list[dict],
    n: int,
    *,
    symbol: str,
    category: str,
    lookback: int = DEFAULT_LOOKBACK,
) -> StrategyContext:
    """Arma el StrategyContext en la barra N usando solo barras <= N.

    `candles` es la serie completa ordenada ascendente por tiempo; N es el
    indice de la barra de decision (close de N). La ventana entregada a las
    estrategias y al pattern TERMINA en N (B1).
    """
    if not candles:
        raise ValueError("build_context requiere al menos una vela")
    if n < 0 or n >= len(candles):
        raise IndexError(f"n={n} fuera de rango (len={len(candles)})")

    start = max(0, n - lookback + 1)
    window = candles[start:n + 1]  # <- termina en N (B1): nada > N entra aca

    pattern = analyze_ohlcv(window)

    close_n = _f(window[-1].get("close"))
    prev_close = _f(window[-2].get("close")) if len(window) >= 2 else None
    change_24h = None
    if close_n is not None and prev_close not in (None, 0):
        change_24h = round((close_n / prev_close - 1) * 100, 4)

    snapshot = TokenSnapshot(
        chain=category,            # parity con forex_collector: chain por categoria
        token_address=symbol,      # y token_address == symbol (no hay address en forex)
        category=category,
        symbol=symbol,
        price=close_n,
        volume_24h=_f(window[-1].get("volume")),
        price_change_24h=change_24h,
        raw={"candles": window, "backtest": True, "bar_index": n},
    )

    # B11: news/pro/macro/learned_weights sin historia en v1 -> None/empty.
    return StrategyContext(
        snapshot=snapshot,
        candles=window,
        pattern=pattern,
        pro=None,
        news_label="no_recent_news",
        news_score=0,
        macro={},
    )


def context_completeness(ctx: StrategyContext) -> ContextCompleteness:
    """Reporta que % del contexto quedo con dato real (B11). 'Poblado' es mas
    estricto que 'no None': un pattern 'insufficient_chart_data' o un news_label
    en su default NO cuentan como informacion real."""
    pattern_ok = (
        ctx.pattern is not None
        and getattr(ctx.pattern, "label", "") not in ("", "insufficient_chart_data")
    )
    checks = {
        "price": ctx.snapshot.price is not None,
        "candles": bool(ctx.candles),
        "pattern": pattern_ok,
        "pro": ctx.pro is not None,
        "news": bool(ctx.news_label) and ctx.news_label != "no_recent_news",
        "macro": bool(ctx.macro),
    }
    populated = sum(1 for value in checks.values() if value)
    total = len(checks)
    missing = [key for key, value in checks.items() if not value]
    return ContextCompleteness(
        populated=populated,
        total=total,
        pct=round(populated / total * 100, 1),
        missing=missing,
    )


def context_field_names() -> set[str]:
    """Nombres de campo del StrategyContext, para el test de paridad con el
    contexto vivo: si alguien agrega un campo a StrategyContext y no lo refleja
    aca, el test de S2 lo cachea."""
    return {f.name for f in fields(StrategyContext)}


def _f(value, fallback=None):
    try:
        if value is None:
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback
