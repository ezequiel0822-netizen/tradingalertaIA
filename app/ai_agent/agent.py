"""v3.13.0 — el agente IA: decide (Thompson), respeta límites duros y aprende.

No envía órdenes: eso lo hace el job a través de `mt5_demo_trader` (único lugar con
`order_send`). Acá vive la lógica pura de decisión, los límites propios del agente y
el aprendizaje desde los paper trades cerrados. Todo soft-fail del lado del job.

v3.14.0 — v2 (opt-in `AI_AGENT_VERSION=2`, pre-registro
research/AGENTE_IA_V2_PREREGISTRO_2026-10-06.md): 24 features, exploración mínima con
riesgo reducido y presupuesto propio, ajuste de realismo con el P&L REAL de MT5 y un
`policy_tag` por decisión. v1 queda intacto (default) y con su propio modelo.

v3.14.1 — adenda 2026-10-07 (research/AGENTE_IA_V2_ADENDA_2026-10-07_oro.md): el oro de
"precio mezclado" (abierto con el futuro de Yahoo, marcado con el spot de MT5) no es
mercado. La MEDICIÓN lo excluye siempre; con `PAPER_PRICE_FROM_MT5=true` el agente
además no aprende de él ni lo usa en ĝ, y el tag v2 suma `|px1` (modelo reconstruido
sin oro mezclado) o `|px0` (todavía no reconstruido: no cuenta).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable

import numpy as np

from app.ai_agent.features import FEATURE_NAMES_V2, feature_names_for, parse_utc
from app.ai_agent.model import LinearThompson
from app.learning.price_source import is_mixed_price_trade
from app.learning.trade_outcomes import is_artifact, r_multiple
from app.utils.time_utils import utc_now

MODEL_STATE_KEY = "ai_agent_model_v1"
MODEL_STATE_KEYS = {1: MODEL_STATE_KEY, 2: "ai_agent_model_v2"}
EVALUATION_DOC = "research/AGENTE_IA_PREREGISTRO_2026-10-05.md"
EVALUATION_DOCS = {1: EVALUATION_DOC, 2: "research/AGENTE_IA_V2_PREREGISTRO_2026-10-06.md"}

# Ajuste de realismo (pre-registro v2 §1.2): media encogida de R_mt5 − R_paper.
GAP_PRIOR_N = 5
GAP_CLIP = (-1.0, 0.25)
# Si a los N días de cerrado el paper la posición de MT5 no aparece cerrada, se
# deja de buscar (mt5_status = 'unavailable').
MT5_GIVE_UP_DAYS = 7

ACTED = ("execute", "explore")


@dataclass(frozen=True)
class Decision:
    mean: float
    sd: float
    sampled: float
    gap: float
    intended: str                 # execute | explore | skip
    risk_cap_pct: float | None    # riesgo máx. de la orden (None si skip)


def _version_of(row: dict[str, Any]) -> int:
    try:
        return int(row.get("agent_version") or 1)
    except (TypeError, ValueError):
        return 1


def single_source_decision(row: dict[str, Any]) -> bool:
    """El paper trade de la decisión tiene UNA fuente de precio (v3.14.1, adenda 2)."""
    return bool(str(row.get("trade_price_source") or "").strip())


def mixed_gold_decision(row: dict[str, Any]) -> bool:
    """Decisión sobre un paper trade de "oro mezclado" (adenda 2026-10-07): oro cuyo
    paper trade no tiene fuente única de precio (`trade_price_source` NULL)."""
    return is_mixed_price_trade({"category": row.get("category"),
                                 "price_source": row.get("trade_price_source")})


class AiAgent:
    def __init__(self, settings, repository) -> None:
        self.settings = settings
        self.repository = repository
        self.version = 2 if int(getattr(settings, "ai_agent_version", 1) or 1) == 2 else 1
        self.feature_names = feature_names_for(self.version)

    @property
    def dim(self) -> int:
        return len(self.feature_names)

    # ------------------------------------------------------------------ modelo
    def load_model(self) -> LinearThompson:
        return LinearThompson.from_json(
            self.repository.get_state(MODEL_STATE_KEYS[self.version]),
            self.feature_names,
            float(self.settings.ai_agent_prior_var),
            float(self.settings.ai_agent_noise_var),
        )

    def save_model(self, model: LinearThompson) -> None:
        self.repository.set_state(MODEL_STATE_KEYS[self.version], model.to_json())

    def price_fix_on(self) -> bool:
        """v3.14.1: PAPER_PRICE_FROM_MT5 (una sola fuente de precio por paper trade)."""
        return bool(getattr(self.settings, "paper_price_from_mt5", False))

    def policy_tag(self, model: LinearThompson | None = None) -> str:
        """Identifica la configuración que tomó cada decisión: la evaluación cuenta
        solo las filas con el tag pre-registrado.

        v3.14.1 (adenda 2026-10-07): con PAPER_PRICE_FROM_MT5, el tag v2 suma `|px1`
        si el modelo se reconstruyó sin oro mezclado y `|px0` si todavía no."""
        s = self.settings
        core = (f"r{float(s.ai_agent_risk_pct):.2f}|thr{float(s.ai_agent_min_edge_r):.2f}"
                f"|pv{float(s.ai_agent_prior_var):.2f}|nv{float(s.ai_agent_noise_var):.2f}")
        if self.version == 1:
            return f"v1|{core}"
        tag = (f"v2|eps{self._explore_pct():.2f}|xr{float(s.ai_agent_explore_risk_pct):.2f}"
               f"|{core}|xmax{int(s.ai_agent_explore_max_per_day)}"
               f"|xstop{float(s.ai_agent_explore_daily_stop_r):.1f}")
        if self.price_fix_on():
            if model is None:
                model = self.load_model()
            tag += "|px1" if self.model_is_clean(model) else "|px0"
        return tag

    @staticmethod
    def model_is_clean(model: LinearThompson) -> bool:
        """El modelo se armó sin oro mezclado (warm start con --exclude-mixed-gold)."""
        return bool((model.meta or {}).get("excludes_mixed_gold"))

    def _explore_pct(self) -> float:
        return min(max(float(getattr(self.settings, "ai_agent_explore_pct", 0.0) or 0.0), 0.0), 1.0)

    def explore_weight(self) -> float:
        """Peso de una exploración en el idioma de riesgo de la explotación (0.10/0.50)."""
        risk = float(self.settings.ai_agent_risk_pct)
        return float(self.settings.ai_agent_explore_risk_pct) / risk if risk > 0 else 0.0

    # ----------------------------------------------------------------- decisión
    def decide(self, model: LinearThompson, x: list[float], paper_trade_id: int
               ) -> tuple[float, float, float, str]:
        """v1: (media, desvío, puntaje muestreado, 'execute'|'skip'). El azar es
        reproducible: semilla = (AI_AGENT_SEED, id del paper trade)."""
        rng = np.random.default_rng([int(self.settings.ai_agent_seed), int(paper_trade_id)])
        mean, sd, sampled = model.sample_score(x, rng)
        intended = "execute" if sampled > float(self.settings.ai_agent_min_edge_r) else "skip"
        return mean, sd, sampled, intended

    def choose(self, model: LinearThompson, x: list[float], paper_trade_id: int) -> Decision:
        """Decisión completa de la versión activa. v1 = `decide` tal cual. v2 =
        Thompson + ajuste de realismo; si no explota, explora con prob. ε."""
        if self.version == 1:
            mean, sd, sampled, intended = self.decide(model, x, paper_trade_id)
            risk = float(self.settings.ai_agent_risk_pct) if intended == "execute" else None
            return Decision(mean, sd, sampled, 0.0, intended, risk)
        seed = int(self.settings.ai_agent_seed)
        rng = np.random.default_rng([seed, int(paper_trade_id), 2])
        mean, sd, sampled = model.sample_score(x, rng)
        gap = self.realism_gap()
        if sampled + gap > float(self.settings.ai_agent_min_edge_r):
            return Decision(mean, sd, sampled, gap, "execute",
                            float(self.settings.ai_agent_risk_pct))
        eps = self._explore_pct()
        u = float(np.random.default_rng([seed, int(paper_trade_id), 2, 1]).random())
        if eps > 0 and u < eps:
            return Decision(mean, sd, sampled, gap, "explore",
                            float(self.settings.ai_agent_explore_risk_pct))
        return Decision(mean, sd, sampled, gap, "skip", None)

    def realism_gap(self, rows: list[dict[str, Any]] | None = None) -> float:
        """ĝ = Σ(R_mt5 − R_paper)/(n + 5) sobre las ejecuciones v2 con ambos R,
        acotado a [−1, +0.25]. 0 sin datos (no hay con qué ajustar).

        v3.14.1 (adenda 2): con PAPER_PRICE_FROM_MT5 solo cuentan las ejecuciones cuyo
        paper trade tiene fuente única. Antes del fix la orden de MT5 usaba el SL/TP del
        paper sobre OTRA entrada (NZDUSD #26: stop real de 0.4 pips → R_mt5 +10.95 vs
        +1.69 en paper) y ĝ quedaba clavado en el tope."""
        if rows is None:
            rows = self.repository.fetch_ai_agent_decisions(limit=100000)
        fix = self.price_fix_on()
        diffs = [float(d["mt5_r"]) - float(d["reward_r"]) for d in rows
                 if _version_of(d) == 2 and int(d.get("executed") or 0) == 1
                 and d.get("mt5_r") is not None and d.get("reward_r") is not None
                 and not (fix and not single_source_decision(d))]
        if not diffs:
            return 0.0
        g = sum(diffs) / (len(diffs) + GAP_PRIOR_N)
        return float(min(max(g, GAP_CLIP[0]), GAP_CLIP[1]))

    # ---------------------------------------------------------- límites propios
    def guardrail_block(self, now: datetime | None = None, kind: str = "execute") -> str | None:
        """Motivo para NO ejecutar (límites del agente), o None si puede.
        `kind='explore'` agrega el presupuesto propio de la exploración."""
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
        if kind == "explore":
            explored = [d for d in executed if d.get("intended") == "explore"]
            x_max = int(self.settings.ai_agent_explore_max_per_day)
            x_today = sum(1 for d in explored
                          if str(d.get("created_at") or "").startswith(today))
            if x_today >= x_max:
                return f"máx. {x_max} exploraciones por día"
            x_r = self.realized_r_today(explored, today)
            x_stop = float(self.settings.ai_agent_explore_daily_stop_r)
            if x_r <= -x_stop:
                return f"stop diario de exploración ({x_r:+.2f}R <= -{x_stop:g}R)"
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
        """Registra el R del paper trade de cada decisión ya cerrada (de cualquier
        versión: es la medición) y actualiza el modelo ACTIVO solo con las decisiones
        de su versión. Devuelve cuántas observaciones incorporó el modelo. Artifacts y
        trades sin R se marcan como procesados sin aprender (no se reintentan).

        v3.14.1: con PAPER_PRICE_FROM_MT5, el oro mezclado se registra (su R queda a la
        vista, la medición lo excluye) pero el modelo NO aprende de él."""
        now_iso = (now or utc_now()).isoformat()
        pending = self.repository.fetch_ai_agent_decisions(pending_reward_only=True)
        closed = [d for d in pending
                  if str(d.get("trade_status") or "open") != "open" and d.get("trade_closed_at")]
        if not closed:
            return 0
        model = self.load_model()
        learned = 0
        fix = self.price_fix_on()
        for d in sorted(closed, key=lambda r: int(r["id"])):
            trade = self.repository.fetch_paper_trade(int(d["paper_trade_id"]))
            r = None if (not trade or is_artifact(trade)) else r_multiple(trade)
            if r is None:
                self.repository.update_ai_agent_decision(int(d["id"]), {"rewarded_at": now_iso})
                continue
            self.repository.update_ai_agent_decision(
                int(d["id"]), {"reward_r": float(r), "rewarded_at": now_iso})
            if fix and is_mixed_price_trade(trade):
                continue
            try:
                x = json.loads(d["features_json"])
            except (TypeError, ValueError):
                continue
            if _version_of(d) != self.version or len(x) != self.dim:
                continue
            model.update(x, r)
            learned += 1
        if learned:
            self.save_model(model)
        return learned

    def collect_mt5_outcomes(self, trader_factory: Callable[[], Any],
                             now: datetime | None = None) -> int:
        """v2 §1.3: R REAL de MT5 de cada decisión ejecutada cuyo paper trade cerró.
        Solo lectura (`closed_position_outcome`). Crea el trader SOLO si hay algo
        pendiente. Devuelve cuántas registró."""
        now = now or utc_now()
        pending = [d for d in self.repository.fetch_ai_agent_decisions(limit=2000)
                   if int(d.get("executed") or 0) == 1 and not d.get("mt5_status")
                   and d.get("demo_request_id") and d.get("trade_closed_at")
                   and str(d.get("trade_status") or "open") != "open"]
        if not pending:
            return 0
        trader = trader_factory()
        done = 0
        for d in pending:
            order = self.repository.fetch_demo_order_for_request(int(d["demo_request_id"]))
            out = None
            if order and order.get("order_ticket") and order.get("stop_loss") is not None:
                out = trader.closed_position_outcome(int(order["order_ticket"]),
                                                     float(order["stop_loss"]))
            if out and out.get("r") is not None:
                self.repository.update_ai_agent_decision(int(d["id"]), {
                    "mt5_r": float(out["r"]), "mt5_profit_usd": out.get("profit_usd"),
                    "mt5_status": "closed"})
                done += 1
                continue
            closed_at = parse_utc(d.get("trade_closed_at"))
            if closed_at is not None and now - closed_at > timedelta(days=MT5_GIVE_UP_DAYS):
                self.repository.update_ai_agent_decision(int(d["id"]), {
                    "mt5_profit_usd": (out or {}).get("profit_usd"),
                    "mt5_status": "unavailable"})
        return done

    # ----------------------------------------------------------------- medición
    def scoreboard(self, version: int | None = None, policy_tag: str | None = None
                   ) -> dict[str, Any]:
        """Valor de la política vs 'no operar' (0) y 'ejecutar todo', sobre las
        decisiones ya cerradas con R (el criterio pre-registrado). Exploración con
        peso `explore_weight()`. Sin filtros = todas las filas.

        v3.14.1 (adenda 2026-10-07): el oro mezclado NO se mide (siempre); se cuenta
        aparte en `excluded_mixed_gold`."""
        rows = self.repository.fetch_ai_agent_decisions(limit=100000)
        if version is not None:
            rows = [d for d in rows if _version_of(d) == int(version)]
        if policy_tag is not None:
            rows = [d for d in rows if d.get("policy_tag") == policy_tag]
        with_r = [d for d in rows if d.get("reward_r") is not None]
        done = [d for d in with_r if not mixed_gold_decision(d)]
        w_x = self.explore_weight()
        weight = {"execute": 1.0, "explore": w_x}
        r = np.array([float(d["reward_r"]) for d in done]) if done else np.array([])
        w = np.array([weight.get(d["intended"], 0.0) for d in done]) if done else np.array([])
        exploit = np.array([1.0 if d["intended"] == "execute" else 0.0 for d in done]) \
            if done else np.array([])
        explore_r = [float(d["reward_r"]) for d in done if d["intended"] == "explore"]
        mt5 = [d for d in rows if d.get("mt5_status") == "closed"]
        policy = w * r
        return {
            "decisions": len(rows),
            "intended_execute": sum(1 for d in rows if d["intended"] == "execute"),
            "intended_explore": sum(1 for d in rows if d["intended"] == "explore"),
            "executed": sum(1 for d in rows if int(d.get("executed") or 0) == 1),
            "rewarded": len(done),
            "excluded_mixed_gold": len(with_r) - len(done),
            "policy_sum_r": float(policy.sum()) if len(done) else 0.0,
            "policy_mean_r": float(policy.mean()) if len(done) else 0.0,
            "exploit_sum_r": float((exploit * r).sum()) if len(done) else 0.0,
            "explore_n": len(explore_r),
            "explore_mean_r": float(np.mean(explore_r)) if explore_r else 0.0,
            "execute_all_mean_r": float(r.mean()) if len(done) else 0.0,
            "executed_sum_r": float(sum(float(d["reward_r"]) for d in done
                                        if int(d.get("executed") or 0) == 1)),
            "mt5_closed": len(mt5),
            "mt5_profit_usd": float(sum(float(d.get("mt5_profit_usd") or 0.0) for d in mt5)),
            "mt5_r_sum": float(sum(float(d["mt5_r"]) for d in mt5 if d.get("mt5_r") is not None)),
            "realism_gap": self.realism_gap(rows),
        }

    def status_text(self, version: str) -> str:
        on = bool(getattr(self.settings, "enable_ai_agent", False))
        model = self.load_model()
        tag = self.policy_tag(model)
        # v3.14.1: la medición es la de la configuración ACTIVA (su tag); las
        # decisiones de otros tags (p. ej. antes del fix del oro) se cuentan aparte.
        sb = self.scoreboard(version=self.version, policy_tag=tag)
        all_v = self.scoreboard(version=self.version)
        lines = [
            f"Agente IA (sandbox demo) — {version}",
            f"Estado: {'ENCENDIDO' if on else 'APAGADO (ENABLE_AI_AGENT=false)'}",
            f"Versión del agente: v{self.version} ({tag})",
            f"Experiencia: aprendió de {model.n} trades cerrados",
            f"Decisiones con este tag: {sb['decisions']} | quiso ejecutar "
            f"{sb['intended_execute']} | exploró {sb['intended_explore']} | "
            f"ejecutadas en MT5 {sb['executed']}",
        ]
        others = all_v["decisions"] - sb["decisions"]
        if others:
            lines.append(f"Decisiones v{self.version} con otro tag (no cuentan acá): {others}")
        if self.version == 2 and self.price_fix_on():
            lines.append(
                "Precio: MT5 de punta a punta (PAPER_PRICE_FROM_MT5) | modelo sin oro "
                f"mezclado: {'sí' if self.model_is_clean(model) else 'NO — reconstruirlo (ver adenda 2026-10-07)'}")
        excluded = sb.get("excluded_mixed_gold") or 0
        lines += [
            "",
            f"Medición (decisiones cerradas: {sb['rewarded']}"
            + (f"; sin {excluded} de oro con precio mezclado" if excluded else "") + "):",
            f"  Agente:        {sb['policy_sum_r']:+.2f}R total ({sb['policy_mean_r']:+.3f}R por candidato)",
            f"  Ejecutar todo: {sb['execute_all_mean_r']:+.3f}R por candidato",
            "  No operar:     +0.000R",
        ]
        if self.version == 2:
            lines += [
                f"  Solo explotación: {sb['exploit_sum_r']:+.2f}R | exploraciones: "
                f"{sb['explore_n']} (media {sb['explore_mean_r']:+.2f}R, pesan "
                f"{self.explore_weight():.2f})",
                f"  MT5 real: {sb['mt5_closed']} cerradas, {sb['mt5_profit_usd']:+.2f} USD, "
                f"{sb['mt5_r_sum']:+.2f}R | ajuste de realismo {sb['realism_gap']:+.2f}R",
            ]
        else:
            lines.append(f"  Lo ejecutado en MT5 sumó {sb['executed_sum_r']:+.2f}R (precio paper)")
        lines += ["", self._beliefs_header()]
        for name, x in self._belief_vectors():
            mu, sd = model.predict(x)
            lines.append(f"  {name:17} {mu:+.2f}R ± {sd:.2f}")
        if self.version == 2:
            coef = model.mean()
            new = ", ".join(f"{n} {coef[i]:+.2f}" for i, n in enumerate(FEATURE_NAMES_V2)
                            if i >= 16)
            lines.append(f"  Pesos de las features nuevas: {new}")
        block = self.guardrail_block() if on else None
        lines += ["", f"Límites hoy: {'OK' if block is None else block}"]
        if on and self.version == 2 and self._explore_pct() > 0:
            xb = self.guardrail_block(kind="explore")
            lines.append(f"Exploración hoy: {'OK' if xb is None else xb}")
        lines += [f"Evaluación pre-registrada: {EVALUATION_DOCS[self.version]}",
                  "Solo demo. Real-money bloqueado por código."]
        return "\n".join(lines)

    def _beliefs_header(self) -> str:
        if self.version == 1:
            return "Lo que cree hoy (R esperado, contexto neutro, long):"
        return "Lo que cree hoy (R esperado en el contexto medio de sus últimos candidatos):"

    def _belief_vectors(self) -> list[tuple[str, list[float]]]:
        """v1: contexto neutro (como siempre). v2: el vector MEDIO de los últimos 50
        candidatos de cada estrategia (el neutro pondría el costo en 0 y engaña);
        si no hay candidatos v2, cae al neutro."""
        out = []
        rows = [] if self.version == 1 else [
            d for d in self.repository.fetch_ai_agent_decisions(limit=2000)
            if _version_of(d) == self.version]
        for short, full, idx in (("session_breakout", "forex_session_breakout", 1),
                                 ("mean_reversion", "mean_reversion", 2),
                                 ("momentum", "momentum", 3)):
            xs = []
            for d in rows:
                if d.get("strategy_name") != full or len(xs) >= 50:
                    continue
                try:
                    x = json.loads(d["features_json"])
                except (TypeError, ValueError):
                    continue
                if len(x) == self.dim:
                    xs.append(x)
            if xs:
                out.append((short, [sum(c) / len(xs) for c in zip(*xs)]))
            else:
                x = [0.0] * self.dim
                x[0], x[idx] = 1.0, 1.0
                out.append((short, x))
        return out

    def summary_line(self, today: str) -> str:
        """Una línea para el resumen diario de Telegram."""
        rows = [d for d in self.repository.fetch_ai_agent_decisions(limit=5000)
                if _version_of(d) == self.version]
        todays = [d for d in rows if str(d.get("created_at") or "").startswith(today)]
        acted = sum(1 for d in todays if d["intended"] in ACTED)
        sent = sum(1 for d in todays if int(d.get("executed") or 0) == 1)
        sb = self.scoreboard(version=self.version, policy_tag=self.policy_tag())
        return (f"Agente IA v{self.version}: hoy {len(todays)} candidatos, quiso operar "
                f"{acted}, a MT5 {sent} | acumulado {sb['policy_sum_r']:+.2f}R vs "
                f"ejecutar todo {sb['execute_all_mean_r'] * sb['rewarded']:+.2f}R "
                f"(n={sb['rewarded']})")
