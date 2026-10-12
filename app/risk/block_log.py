"""v3.17.0 — Contador de frenados ("log de descartes" del plan v3.17, P2 #14).

Cuenta por día POR QUÉ se frenó cada candidato: tope de trades abiertos, cooldown,
kill-switch, sizing, ya abierto, o los gates del camino a MT5. Solo registro: no cambia
ninguna decisión. Opt-in `ENABLE_DISCARD_LOG`; se ve con `/frenados` (el `/descartes`
viejo sigue mostrando las ALERTAS no enviadas, que es otra cosa).

Puro: normaliza el motivo para contar por tipo (sin números ni detalles).
"""

from __future__ import annotations

import re

STAGE_RISK = "riesgo"          # risk_manager.check_can_open_trade
STAGE_SIZING = "sizing"        # position_sizer: tamaño inválido
STAGE_OPEN = "abierto"         # ya hay un paper trade abierto del mismo símbolo
STAGE_MT5 = "mt5"              # gates del camino a MT5 que NO es del agente
STAGE_AGENT = "agente"         # límites del agente (se leen de ai_agent_decisions)


def reason_code(text: object) -> str:
    """Motivo sin detalles, para agrupar: corta en ' (' y en ':' y cambia números por N.

    'max_open_trades_total reached (5/5)' -> 'max_open_trades_total reached'
    'kill switch active: daily drawdown -3.1%' -> 'kill switch active'
    'máx. 3 posiciones del agente abiertas' -> 'máx. n posiciones del agente abiertas'
    """
    s = str(text or "").strip()
    for sep in (" (", ":"):
        idx = s.find(sep)
        if idx > 0:
            s = s[:idx]
    s = re.sub(r"\d+(?:[.,]\d+)?", "N", s).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s[:80] or "sin motivo"
