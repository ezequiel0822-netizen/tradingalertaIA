"""v3.2.0 / Fase C — ContinuousLearner: una leccion razonada por trade cerrado.

Al cerrar trades, este job (escaneo periodico, NO hook inline) le pide al LLM local
una leccion (`analyze_win` / `analyze_loss`) y la registra en la tabla `trade_lessons`.
Agrupa lecciones por clave (estrategia|categoria|direccion|outcome); cuando N comparten
clave, **PROPONE** revisar esa combinacion por Telegram — NO aplica ningun cambio.

PRINCIPIO INAMOVIBLE (igual que toda la serie v3): es read/registro. No toca ejecucion,
ni el gate, ni `order_send`, ni real-money. El LLM sigue SUBTRACTIVO: lo mas que hace es
*proponer* para que el humano decida. Opt-in OFF (`enable_continuous_learner` +
`store_trade_lessons`); soft-fail total: si esta apagado, Ollama no responde, o algo
falla, el bot corre EXACTAMENTE igual.

Costo acotado: procesa como mucho `max_per_cycle` trades pendientes por ciclo (respeta
el cap de llamadas LLM y la latencia). Idempotente: cada paper_trade recibe a lo sumo
una leccion (UNIQUE paper_trade_id); los ya procesados se saltan barato.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.config.settings import Settings
from app.learning.trade_outcomes import is_artifact, r_multiple, session_of
from app.utils.time_utils import utc_now_iso

logger = logging.getLogger(__name__)

# Cuantas lecciones con la misma clave hacen falta para PROPONER una revision.
DEFAULT_PROPOSAL_THRESHOLD = 10
# Cuantos trades pendientes se analizan por ciclo (cap de costo/latencia LLM).
DEFAULT_MAX_PER_CYCLE = 3


@dataclass
class ContinuousLearnerSummary:
    enabled: bool = False
    scanned: int = 0
    lessons_created: int = 0
    proposals_made: int = 0
    skipped_no_text: int = 0


def _lesson_key(strategy_name: str, category: str, direction: str, outcome: str) -> str:
    return f"{strategy_name}|{category}|{direction}|{outcome}"


class ContinuousLearner:
    """Extrae y registra una leccion por trade cerrado; propone (no aplica) ajustes."""

    def __init__(
        self,
        settings: Settings,
        repository: Any,
        reasoner: Any | None = None,
        notifier: Any | None = None,
        max_per_cycle: int = DEFAULT_MAX_PER_CYCLE,
        proposal_threshold: int = DEFAULT_PROPOSAL_THRESHOLD,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self._reasoner = reasoner
        self._notifier = notifier
        self.max_per_cycle = max_per_cycle
        self.proposal_threshold = proposal_threshold

    # -- gating ------------------------------------------------------------ #
    def _enabled(self) -> bool:
        # Requiere los TRES flags: master, persistencia (sin corpus no hay agrupacion ni
        # propuestas), y el asesor LLM (sin el, la leccion siempre seria None y el learner
        # escanearia sin producir nada). Asi queda IDLE limpio si falta cualquiera.
        return bool(
            getattr(self.settings, "enable_continuous_learner", False)
            and getattr(self.settings, "store_trade_lessons", False)
            and getattr(self.settings, "enable_llm_advisor", False)
        )

    def _reasoner_or_none(self) -> Any | None:
        if self._reasoner is None:
            try:
                from app.intelligence.reasoner import TradingReasoner

                self._reasoner = TradingReasoner(self.settings)
            except Exception:  # pragma: no cover - defensivo
                logger.warning("ContinuousLearner: no se pudo crear el reasoner")
                return None
        return self._reasoner

    # -- core -------------------------------------------------------------- #
    def run(self) -> ContinuousLearnerSummary:
        if not self._enabled():
            return ContinuousLearnerSummary(enabled=False)
        reasoner = self._reasoner_or_none()
        if reasoner is None:
            return ContinuousLearnerSummary(enabled=True)

        summary = ContinuousLearnerSummary(enabled=True)
        try:
            already = self.repository.fetch_trade_lesson_ids()
            closed = self.repository.fetch_closed_paper_trades(limit=500)
        except Exception:
            logger.exception("ContinuousLearner: fetch fallo; soft-fail")
            return summary

        for trade in closed:
            # Cap por ciclo sobre los INTENTOS al LLM (scanned), no sobre lecciones
            # creadas: si el advisor devolviera None, igual no se dispara una tormenta de
            # llamadas ni un rescaneo completo del fetch.
            if summary.scanned >= self.max_per_cycle:
                break
            try:
                tid = trade.get("id")
                if tid is None or int(tid) in already:
                    continue
                if str(trade.get("status") or "") == "open" or is_artifact(trade):
                    continue
                r = r_multiple(trade)
                if r is None or r == 0:
                    continue  # scratch / no medible -> sin leccion
                summary.scanned += 1
                self._process_trade(trade, r, reasoner, summary)
            except Exception:
                # Un trade que falla no descarta el resto.
                logger.exception("ContinuousLearner: trade fallo; sigo con el resto")
                continue
        return summary

    def _process_trade(
        self, trade: dict, r: float, reasoner: Any, summary: ContinuousLearnerSummary
    ) -> None:
        outcome = "win" if r > 0 else "loss"
        strategy = str(trade.get("strategy_name") or "unknown")
        category = str(trade.get("category") or "unknown")
        direction = str(trade.get("direction") or "unknown")

        ctx = {
            "symbol": trade.get("symbol"),
            "direction": direction,
            "strategy_name": strategy,
            "entry_price": trade.get("entry_price"),
            "stop_loss": trade.get("stop_loss"),
            "r_multiple": round(r, 2),
            "session": session_of(trade.get("opened_at")),
            "rsi_entry": trade.get("rsi_entry"),
            "atr_value": trade.get("atr_value"),
            "close_reason": trade.get("status"),
        }
        text = reasoner.analyze_win(ctx) if outcome == "win" else reasoner.analyze_loss(ctx)
        if not text:
            # Advisor off / Ollama caido / soft-fail -> no registro; reintenta luego.
            summary.skipped_no_text += 1
            return

        key = _lesson_key(strategy, category, direction, outcome)
        created = self.repository.insert_trade_lesson(
            {
                "paper_trade_id": int(trade["id"]),
                "symbol": trade.get("symbol"),
                "category": category,
                "strategy_name": strategy,
                "direction": direction,
                "outcome": outcome,
                "r_multiple": round(r, 4),
                "lesson": text,
                "lesson_key": key,
                "created_at": utc_now_iso(),
            }
        )
        if created:
            summary.lessons_created += 1
            self._maybe_propose(key, text, summary)

    def _maybe_propose(
        self, key: str, last_lesson: str, summary: ContinuousLearnerSummary
    ) -> None:
        """Si >= threshold lecciones comparten clave y aun no se propuso esta clave,
        manda UNA propuesta por Telegram. NO aplica ningun cambio. Dedupe via
        bot_state para no repetir la propuesta cada ciclo."""
        if self._notifier is None:
            return
        try:
            count = self.repository.count_trade_lessons_by_key(key)
            if count < self.proposal_threshold:
                return
            state_key = f"cl_proposed::{key}"
            if self.repository.get_state(state_key):
                return
            message = (
                f"[ContinuousLearner] {count} lecciones repetidas en '{key}'.\n"
                f"Ultima leccion: {last_lesson}\n\n"
                "PROPUESTA (no la aplico solo): revisa esta combinacion "
                "estrategia/categoria/direccion. La decision de ajustar algo es tuya."
            )
            self._notifier.send_message(message)
            self.repository.set_state(state_key, utc_now_iso())
            summary.proposals_made += 1
        except Exception:
            logger.exception("ContinuousLearner: propuesta fallo; soft-fail")
