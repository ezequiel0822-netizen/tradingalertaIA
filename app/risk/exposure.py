"""v3.5.0 — Exposicion neta USD: cuantas "apuestas al dolar" hay abiertas a la vez.

Motivado por el 2026-06-10: el bot tenia 7 posiciones forex abiertas que eran LA MISMA
apuesta (short EUR/GBP/AUD/NZD + long USDCAD/USDCHF = todas long-USD); un solo movimiento
del dolar (CPI + BOC) las stoppeo a todas juntas (~-7R). Los caps por categoria no ven
correlacion: 7 trades "distintos" pueden ser 1 sola apuesta concentrada.

Convencion: +1 = posicion long-USD, -1 = short-USD, 0 = no-USD/desconocido.
  - USDXXX (USDCAD, USDCHF, USDJPY): long del par = long USD (+1); short = -1.
  - XXXUSD (EURUSD, GBPUSD, AUDUSD, NZDUSD): long del par = SHORT USD (-1); short = +1.

Funciones puras (testeables con dicts); el gate en jobs SOLO bloquea hacia abajo
(paper-only), jamas habilita. Opt-in OFF + soft-fail, como todo lo nuevo.
"""

from __future__ import annotations

from typing import Any


def _clean_symbol(symbol: str) -> str:
    """Normaliza Yahoo ('EURUSD=X') y MT5 ('EURUSD') al par de 6 letras."""
    s = str(symbol or "").upper().strip()
    if s.endswith("=X"):
        s = s[:-2]
    return s


def usd_direction(symbol: str, direction: str) -> int:
    """+1 si la posicion es long-USD, -1 si es short-USD, 0 si el par no tiene USD
    o no se reconoce (p.ej. oro, acciones, memecoins: no entran al neto)."""
    pair = _clean_symbol(symbol)
    if len(pair) != 6 or not pair.isalpha():
        return 0
    is_long = str(direction or "long").lower() != "short"
    if pair.startswith("USD"):
        return 1 if is_long else -1
    if pair.endswith("USD"):
        return -1 if is_long else 1
    return 0


def net_usd_exposure(open_trades: list[dict[str, Any]]) -> int:
    """Suma de usd_direction sobre los trades abiertos (los que se le pasen — el caller
    decide si filtra por ejecutados a MT5). Positivo = neto long-USD."""
    total = 0
    for t in open_trades:
        total += usd_direction(str(t.get("symbol") or ""), str(t.get("direction") or ""))
    return total


def would_exceed_cap(
    open_trades: list[dict[str, Any]],
    candidate_symbol: str,
    candidate_direction: str,
    max_net: int,
) -> tuple[bool, str]:
    """(True, razon) si abrir el candidato dejaria |exposicion neta USD| > max_net.
    Solo puede BLOQUEAR concentracion adicional: un candidato que reduce o no toca el
    neto (usd_direction 0, o de signo contrario) siempre pasa."""
    cand = usd_direction(candidate_symbol, candidate_direction)
    if cand == 0:
        return False, "sin pata USD"
    current = net_usd_exposure(open_trades)
    projected = current + cand
    if abs(projected) > max_net and abs(projected) > abs(current):
        side = "long-USD" if projected > 0 else "short-USD"
        return True, (
            f"exposicion USD concentrada: abierta={current:+d}, candidato={cand:+d} "
            f"-> {projected:+d} {side} (cap |{max_net}|)"
        )
    return False, f"neto proyectado {projected:+d} dentro del cap"
