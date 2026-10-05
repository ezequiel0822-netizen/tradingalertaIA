"""v3.13.0 — el agente IA: decide (Thompson), respeta límites duros y aprende.

No envía órdenes: eso lo hace el job a través de `mt5_demo_trader` (único lugar con
`order_send`). Acá vive la lógica pura de decisión, los límites propios del agente y
el aprendizaje desde los paper trades cerrados. Todo soft-fail del lado del job.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import numpy as np

from app.ai_agent.features import DIM, FEATURE_NAMES
from app.ai_agent.model import LinearThompson
from app.learning.trade_outcomes import is_artifact, r_multiple
from app.utils.time_utils import utc_now

MODEL_STATE_KEY = "ai_agent_model_v1"
EVALUATION_DOC = "research/AGENTE_IA_PREREGISTRO_2026-10-05.md"


class AiAgent:
    def __init__(self, settings, repository) -> None:
        self.settings = settings
        self.repository = repository

    # ------------------------------------------------------------------ modelo
    def load_model(self) -> LinearThompson:
        return LinearThompson.from_json(
            self.repository.get_state(MODEL_STATE_KEY),
            FEATURE_NAMES,
            float(self.settings.ai_agent_prior_var),
            float(self.settings.ai_agent_noise_var),
        )

    def save_model(self, model: LinearThompson) -> None:
        self.repository.set_state(MODEL_STATE_KEY, model.to_json())

    # ----------------------------------------------------------------- decisión
    def decide(self, model: LinearThompson, x: list[float], paper_trade_id: int
               ) -> tuple[float, float, float, str]:
        """(media, desvío, puntaje muestreado, 'execute'|'skip'). El azar es
        reproducible: semilla = (AI_AGENT_SEED, id del paper trade)."""
        rng = np.random.default_rng([int(self.settings.ai_agent_seed), int(paper_trade_id)])
        mean, sd, sampled = model.sample_score(x, rng)
        intended = "execute" if sampled > float(self.settings.ai_agent_min_edge_r) else "skip"
        return mean, sd, sampled, intended

    # ---------------------------------------------------------- límites propios
    def guardrail_block(self, now: datetime | None = None) -> str | None:
        """Motivo para NO ejecutar (límites del agente), o None si puede."""
        now = now or utc_now()
        today = now.date().isoformat()
        executed = [d for d in self.repository.fetch_ai_agent_decisions(limit=2000)
                    if int(d.get("executed") or 0) == 1]
        max_open = int(self.settings.ai_agent_max_open)
        n_open = sum(1 for d in executed if str(d.get("trade_status") or "") == "open")
        if n_open >= max_open:
            return f"máx. {max_open} posiciones del agente abiertas"
        max_day = int(self.settings.ai_agent_max_trades_per_day)
        n_today = sum(1 for d in executed if str(d.get("created_at") or "").startswith(today))
        if n_today >= max_day:
            return f"máx. {max_day} trades del agente por día"
        r_today = self.realized_r_today(executed, today)
        stop = float(self.settings.ai_agent_daily_stop_r)
        if r_today <= -stop:
            return f"stop diario del agente ({r_today:+.2f}R <= -{stop:g}R)"
        return None

    def realized_r_today(self, executed: list[dict[str, Any]], today: str) -> float:
        total = 0.0
        for d in executed:
            if not str(d.get("trade_closed_at") or "").startswith(today):
                continue
            trade = self.repository.fetch_paper_trade(int(d["paper_trade_id"]))
            if not trade or is_artifact(trade):
                continue
            r = r_multiple(trade)
            if r is not None:
                total += r
        return total

    # ------------------------------------------------------------- aprendizaje
    def learn(self, now: datetime | None = None) -> int:
        """Aprende de cada decisión cuyo paper trade ya cerró. Devuelve cuántas
        observaciones nuevas incorporó. Artifacts y trades sin R se marcan como
        procesados sin aprender (no se reintentan)."""
        now_iso = (now or utc_now()).isoformat()
        pending = self.repository.fetch_ai_agent_decisions(pending_reward_only=True)
        closed = [d for d in pending
                  if str(d.get("trade_status") or "open") != "open" and d.get("trade_closed_at")]
        if not closed:
            return 0
        model = self.load_model()
        learned = 0
        for d in sorted(closed, key=lambda r: int(r["id"])):
            trade = self.repository.fetch_paper_trade(int(d["paper_trade_id"]))
            r = None if (not trade or is_artifact(trade)) else r_multiple(trade)
            if r is None:
                self.repository.update_ai_agent_decision(int(d["id"]), {"rewarded_at": now_iso})
                continue
            x = json.loads(d["features_json"])
            if len(x) != DIM:
                self.repository.update_ai_agent_decision(int(d["id"]), {"rewarded_at": now_iso})
                continue
            model.update(x, r)
            learned += 1
            self.repository.update_ai_agent_decision(
                int(d["id"]), {"reward_r": float(r), "rewarded_at": now_iso})
        self.save_model(model)
        return learned

    # ----------------------------------------------------------------- medición
    def scoreboard(self) -> dict[str, Any]:
        """Valor de la política del agente vs 'no operar' (0) y 'ejecutar todo',
        sobre las decisiones ya cerradas con R (el criterio pre-registrado)."""
        rows = self.repository.fetch_ai_agent_decisions(limit=100000)
        done = [d for d in rows if d.get("reward_r") is not None]
        r = np.array([float(d["reward_r"]) for d in done]) if done else np.array([])
        act = np.array([1.0 if d["intended"] == "execute" else 0.0 for d in done]) if done else np.array([])
        policy = act * r
        return {
            "decisions": len(rows),
            "intended_execute": sum(1 for d in rows if d["intended"] == "execute"),
            "executed": sum(1 for d in rows if int(d.get("executed") or 0) == 1),
            "rewarded": len(done),
            "policy_sum_r": float(policy.sum()) if len(done) else 0.0,
            "policy_mean_r": float(policy.mean()) if len(done) else 0.0,
            "execute_all_mean_r": float(r.mean()) if len(done) else 0.0,
            "executed_sum_r": float(sum(float(d["reward_r"]) for d in done
                                        if int(d.get("executed") or 0) == 1)),
        }

    def status_text(self, version: str) -> str:
        on = bool(getattr(self.settings, "enable_ai_agent", False))
        model = self.load_model()
        sb = self.scoreboard()
        lines = [
            f"Agente IA (sandbox demo) — {version}",
            f"Estado: {'ENCENDIDO' if on else 'APAGADO (ENABLE_AI_AGENT=false)'}",
            f"Experiencia: aprendió de {model.n} trades cerrados",
            f"Decisiones: {sb['decisions']} | quiso ejecutar {sb['intended_execute']} | "
            f"ejecutadas en MT5 {sb['executed']}",
            "",
            f"Medición (decisiones cerradas: {sb['rewarded']}):",
            f"  Agente:        {sb['policy_sum_r']:+.2f}R total ({sb['policy_mean_r']:+.3f}R por candidato)",
            f"  Ejecutar todo: {sb['execute_all_mean_r']:+.3f}R por candidato",
            "  No operar:     +0.000R",
            f"  Lo ejecutado en MT5 sumó {sb['executed_sum_r']:+.2f}R (precio paper)",
            "",
            "Lo que cree hoy (R esperado, contexto neutro, long):",
        ]
        for name, idx in (("session_breakout", 1), ("mean_reversion", 2), ("momentum", 3)):
            x = [0.0] * DIM
            x[0], x[idx] = 1.0, 1.0
            mu, sd = model.predict(x)
            lines.append(f"  {name:17} {mu:+.2f}R ± {sd:.2f}")
        block = self.guardrail_block() if on else None
        lines += ["", f"Límites hoy: {'OK' if block is None else block}",
                  f"Evaluación pre-registrada: {EVALUATION_DOC}",
                  "Solo demo. Real-money bloqueado por código."]
        return "\n".join(lines)
