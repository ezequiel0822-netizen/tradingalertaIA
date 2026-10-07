"""v3.14.0 — reporte del agente IA en SOLO LECTURA (para la revisión semanal).

Abre la DB con `mode=ro` (no escribe nada, no lee el .env, no toca MT5) y resume las
decisiones por versión/política: valor del agente vs "no operar" y "ejecutar todo",
explotación vs exploración, resultado REAL de MT5 (magic 250501) y ajuste de
realismo. Las medias se muestran siempre; la t NO (pre-registro v2 §3).

`--evaluate` corre el criterio pre-registrado de v2 (§4) y se niega antes del
2027-01-11 o con menos de 200 decisiones (salvo que ya sea 2027-04-12: baja potencia).

v3.14.1 — adenda 2026-10-07 (research/AGENTE_IA_V2_ADENDA_2026-10-07_oro.md): el tag
evaluado pasa a ser el original + `|px1` (precio de MT5 de punta a punta + modelo sin
oro mezclado). El tag original se reporta aparte y no decide. El "oro mezclado" (paper
trade de oro sin `price_source`) nunca se mide: se cuenta aparte.

v3.15.0 — agentes sombra (research/AGENTE_IA_SOMBRAS_PREREGISTRO_2026-10-07.md): qué
habrían hecho `codicioso`, `prudente` y `simple` con las mismas decisiones (nunca
operan). Se muestran siempre; `--evaluate` aplica su criterio desde la misma fecha.

  python scripts/ai_agent_report.py
  python scripts/ai_agent_report.py --json
  python scripts/ai_agent_report.py --evaluate
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PREREG_TAG_V2_ORIGINAL = "v2|eps0.20|xr0.10|r0.50|thr0.05|pv0.25|nv1.00|xmax3|xstop2.0"
PREREG_TAG_V2 = PREREG_TAG_V2_ORIGINAL + "|px1"     # adenda 2026-10-07 §3
EVAL_FROM = date(2027, 1, 11)
EVAL_DEADLINE = date(2027, 4, 12)
EVAL_MIN_N = 200
NW_LAGS = 5
T_MIN = 2.50
EXPLORE_WEIGHT = 0.10 / 0.50
LIMITS = {"risk_exploit": 0.50, "risk_explore": 0.10, "per_day": 6, "explore_per_day": 3}


def connect_ro(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def newey_west_t(series: list[float], lags: int = NW_LAGS) -> float | None:
    """t de la media con varianza de largo plazo de Newey-West (Bartlett)."""
    n = len(series)
    if n < 3:
        return None
    m = sum(series) / n
    d = [x - m for x in series]
    lrv = sum(v * v for v in d) / n
    for k in range(1, min(lags, n - 1) + 1):
        gk = sum(d[i] * d[i - k] for i in range(k, n)) / n
        lrv += 2.0 * (1.0 - k / (lags + 1.0)) * gk
    if lrv <= 0:
        return None
    return m / math.sqrt(lrv / n)


def load_decisions(con: sqlite3.Connection) -> list[dict]:
    cols = {r[1] for r in con.execute("PRAGMA table_info(ai_agent_decisions)")}
    extra = [c for c in ("agent_version", "policy_tag", "risk_cap_pct", "realism_gap",
                         "mt5_r", "mt5_profit_usd", "mt5_status") if c in cols]
    pcols = {r[1] for r in con.execute("PRAGMA table_info(paper_trades)")}
    psrc = "p.price_source" if "price_source" in pcols else "NULL"
    sel = ", ".join(["d.id", "d.created_at", "d.symbol", "d.category", "d.strategy_name",
                     "d.direction", "d.intended", "d.executed", "d.block_reason",
                     "d.reward_r", "d.demo_request_id", "d.mean_r", "d.std_r"]
                    + [f"d.{c}" for c in extra])
    rows = con.execute(
        f"SELECT {sel}, p.status AS trade_status, p.category AS trade_category, "
        f"{psrc} AS trade_price_source FROM ai_agent_decisions d "
        "LEFT JOIN paper_trades p ON p.id = d.paper_trade_id ORDER BY d.id").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["agent_version"] = int(d.get("agent_version") or 1)
        d["mixed_gold"] = is_mixed_gold(d)
        out.append(d)
    return out


def is_mixed_gold(d: dict) -> bool:
    """Oro mezclado (adenda 2026-10-07): paper trade de oro sin fuente única de precio."""
    cat = str(d.get("trade_category") or d.get("category") or "").lower()
    return cat == "gold" and not str(d.get("trade_price_source") or "").strip()


def load_closed_trades(con: sqlite3.Connection) -> list[dict]:
    """Paper trades forex/oro cerrados (el modelo de la sombra `simple` aprende de ellos)."""
    rows = con.execute(
        "SELECT * FROM paper_trades WHERE category IN ('forex', 'gold') "
        "AND status != 'open' AND closed_at IS NOT NULL").fetchall()
    return [dict(r) for r in rows]


def shadow_population(rows: list[dict], tag: str | None = PREREG_TAG_V2) -> list[dict]:
    """Decisiones v2 (del tag, si se da) con R y sin oro mezclado."""
    return [d for d in rows if d["agent_version"] == 2 and d.get("reward_r") is not None
            and not d.get("mixed_gold") and (tag is None or d.get("policy_tag") == tag)]


def shadows_for(pop: list[dict], closed: list[dict]) -> dict:
    """Marcador de las sombras sobre una población (import perezoso: numpy)."""
    sys.path.insert(0, str(ROOT))
    from app.ai_agent.shadows import shadow_decisions, shadow_scoreboard

    flags = shadow_decisions(pop, closed)
    return {"flags": flags, "board": shadow_scoreboard(pop, flags)}


def weight(intended: str) -> float:
    return {"execute": 1.0, "explore": EXPLORE_WEIGHT}.get(intended, 0.0)


def summarize(rows: list[dict]) -> dict:
    with_r = [d for d in rows if d.get("reward_r") is not None]
    done = [d for d in with_r if not d.get("mixed_gold")]       # adenda 2026-10-07
    r = [float(d["reward_r"]) for d in done]
    v = [weight(d["intended"]) * float(d["reward_r"]) for d in done]
    mt5 = [d for d in rows if d.get("mt5_status") == "closed"]
    paired = [d for d in mt5 if d.get("mt5_r") is not None and d.get("reward_r") is not None]
    # adenda 2: real − paper solo con fuente única (antes del fix la orden de MT5 usaba
    # el SL/TP del paper sobre otra entrada: NZDUSD #26 dio +10.95R real vs +1.69 paper)
    single = [d for d in paired if str(d.get("trade_price_source") or "").strip()]
    gaps = [float(d["mt5_r"]) - float(d["reward_r"]) for d in single]
    by_strat: dict[str, list[float]] = defaultdict(list)
    for d in done:
        by_strat[str(d.get("strategy_name"))].append(float(d["reward_r"]))
    excluded = [d for d in with_r if d.get("mixed_gold")]
    return {
        "decisions": len(rows),
        "with_r": len(done),
        "excluded_mixed_gold": len(excluded),
        "excluded_mixed_gold_sum_r": round(sum(float(d["reward_r"]) for d in excluded), 3),
        "intended": {k: sum(1 for d in rows if d["intended"] == k)
                     for k in ("execute", "explore", "skip")},
        "sent_to_mt5": sum(1 for d in rows if int(d.get("executed") or 0) == 1),
        "blocked": sum(1 for d in rows if d.get("block_reason")),
        "policy_sum_r": round(sum(v), 3),
        "policy_mean_r": round(sum(v) / len(v), 4) if v else None,
        "exploit_sum_r": round(sum(float(d["reward_r"]) for d in done
                                   if d["intended"] == "execute"), 3),
        "explore_mean_r": round(sum(float(d["reward_r"]) for d in done
                                    if d["intended"] == "explore")
                                / max(1, sum(1 for d in done if d["intended"] == "explore")), 3),
        "execute_all_mean_r": round(sum(r) / len(r), 4) if r else None,
        "mt5_closed": len(mt5),
        "mt5_profit_usd": round(sum(float(d.get("mt5_profit_usd") or 0) for d in mt5), 2),
        "mt5_minus_paper_mean_r": round(sum(gaps) / len(gaps), 3) if gaps else None,
        "mt5_pre_fix_paired": len(paired) - len(single),
        "by_strategy": {k: {"n": len(x), "mean_r": round(sum(x) / len(x), 3)}
                        for k, x in sorted(by_strat.items())},
        "first": rows[0]["created_at"][:16] if rows else None,
        "last": rows[-1]["created_at"][:16] if rows else None,
    }


def limit_breaches(con: sqlite3.Connection) -> list[str]:
    out = []
    reqs = [dict(r) for r in con.execute(
        "SELECT id, created_at, risk_pct, strategy_name, status FROM demo_trade_requests "
        "WHERE strategy_name LIKE 'ai_agent%'")]
    per_day: dict[str, int] = defaultdict(int)
    explore_day: dict[str, int] = defaultdict(int)
    for q in reqs:
        explore = str(q["strategy_name"]).startswith("ai_agent_explore/")
        cap = LIMITS["risk_explore"] if explore else LIMITS["risk_exploit"]
        if q.get("risk_pct") is not None and float(q["risk_pct"]) > cap + 1e-9:
            out.append(f"request {q['id']}: riesgo {q['risk_pct']}% > {cap}%")
        if q.get("status") == "sent":
            day = str(q["created_at"])[:10]
            per_day[day] += 1
            explore_day[day] += explore
    out += [f"{d}: {n} órdenes del agente > {LIMITS['per_day']}"
            for d, n in per_day.items() if n > LIMITS["per_day"]]
    out += [f"{d}: {n} exploraciones > {LIMITS['explore_per_day']}"
            for d, n in explore_day.items() if n > LIMITS["explore_per_day"]]
    return out


def evaluate_v2(rows: list[dict], con: sqlite3.Connection, today: date) -> dict:
    """Criterio pre-registrado (research/AGENTE_IA_V2_PREREGISTRO_2026-10-06.md §4)."""
    cand = [d for d in rows if d["agent_version"] == 2 and d.get("policy_tag") == PREREG_TAG_V2
            and d.get("reward_r") is not None and not d.get("mixed_gold")]
    if today < EVAL_FROM:
        return {"status": "TODAVIA_NO", "detail": f"la evaluación es desde {EVAL_FROM}"}
    if len(cand) < EVAL_MIN_N and today < EVAL_DEADLINE:
        return {"status": "TODAVIA_NO", "detail": f"{len(cand)} < {EVAL_MIN_N} decisiones"}
    daily: dict[str, float] = defaultdict(float)
    for d in cand:
        daily[str(d["created_at"])[:10]] += weight(d["intended"]) * float(d["reward_r"])
    days = sorted(daily)
    series = [daily[k] for k in days]
    v = [weight(d["intended"]) * float(d["reward_r"]) for d in cand]
    allr = [float(d["reward_r"]) for d in cand]
    half = len(series) // 2
    t = newey_west_t(series)
    breaches = limit_breaches(con)
    crit = {
        "1_media_v_pos": sum(v) / len(v) > 0 if v else False,
        "2_t_nw_ge_2.50": (t is not None and t >= T_MIN),
        "3_v_gt_ejecutar_todo": (sum(v) / len(v) > sum(allr) / len(allr)) if v else False,
        "4_ambas_mitades_pos": bool(half) and sum(series[:half]) > 0 and sum(series[half:]) > 0,
        "5_sin_limites_rotos": not breaches,
    }
    return {"status": "PASA" if all(crit.values()) else "NO PASA",
            "n": len(cand), "days": len(series), "t_nw": t, "criteria": crit,
            "low_power": len(cand) < EVAL_MIN_N, "breaches": breaches}


def evaluate_shadows(rows: list[dict], closed: list[dict], today: date) -> dict:
    """Criterio pre-registrado de las sombras (§4): por sombra, media > 0, t NW ≥ 2.50,
    media > ejecutar todo y ambas mitades > 0, sobre las decisiones `px1`."""
    pop = shadow_population(rows)
    if today < EVAL_FROM:
        return {"status": "TODAVIA_NO", "detail": f"la evaluación es desde {EVAL_FROM}"}
    if len(pop) < EVAL_MIN_N and today < EVAL_DEADLINE:
        return {"status": "TODAVIA_NO", "detail": f"{len(pop)} < {EVAL_MIN_N} decisiones"}
    sys.path.insert(0, str(ROOT))
    from app.ai_agent.shadows import SHADOWS, daily_series, shadow_decisions, shadow_values

    flags = shadow_decisions(pop, closed)
    allr = [float(d["reward_r"]) for d in pop]
    out: dict = {"n": len(pop), "low_power": len(pop) < EVAL_MIN_N, "shadows": {}}
    for name in SHADOWS:
        vals = shadow_values(pop, flags, name)
        v = [x for _, x in vals]
        series = daily_series(vals)
        half = len(series) // 2
        t = newey_west_t(series)
        crit = {
            "1_media_v_pos": (sum(v) / len(v) > 0) if v else False,
            "2_t_nw_ge_2.50": (t is not None and t >= T_MIN),
            "3_v_gt_ejecutar_todo": (sum(v) / len(v) > sum(allr) / len(allr)) if v else False,
            "4_ambas_mitades_pos": bool(half) and sum(series[:half]) > 0
            and sum(series[half:]) > 0,
        }
        out["shadows"][name] = {"status": "PASA" if all(crit.values()) else "NO PASA",
                                "t_nw": t, "criteria": crit, "days": len(series)}
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, default=ROOT / "trading_data" / "trading_alert_ai.db")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--evaluate", action="store_true", help="criterio pre-registrado de v2")
    args = ap.parse_args()

    con = connect_ro(args.db)
    rows = load_decisions(con)
    closed = load_closed_trades(con)
    groups: dict[str, list[dict]] = defaultdict(list)
    for d in rows:
        groups[d.get("policy_tag") or f"v{d['agent_version']} (sin tag)"].append(d)
    report = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "groups": {k: summarize(v) for k, v in groups.items()},
        "prereg_tag_v2": PREREG_TAG_V2,
    }
    for tag, members in groups.items():
        pop = shadow_population(members, tag=None)
        if pop:
            report["groups"][tag]["shadows"] = shadows_for(pop, closed)["board"]
    if args.evaluate:
        today = datetime.now(timezone.utc).date()
        report["evaluation_v2"] = evaluate_v2(rows, con, today)
        report["evaluation_shadows"] = evaluate_shadows(rows, closed, today)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"Agente IA — reporte (solo lectura) {report['generated_utc']}")
    for tag, s in report["groups"].items():
        mark = ("  <- EVALUADA (pre-registro v2 + adenda 2026-10-07)" if tag == PREREG_TAG_V2
                else "  (tag original de v2: se reporta, NO decide — adenda 2026-10-07)"
                if tag == PREREG_TAG_V2_ORIGINAL else "")
        print(f"\n[{tag}]{mark}")
        print(f"  decisiones {s['decisions']} ({s['first']} → {s['last']}), con R {s['with_r']}")
        if s["excluded_mixed_gold"]:
            print(f"  oro con precio mezclado (no se mide): {s['excluded_mixed_gold']} "
                  f"decisiones, suma de su R paper {s['excluded_mixed_gold_sum_r']:+.2f}R")
        print(f"  intención: {s['intended']} | a MT5: {s['sent_to_mt5']} | frenadas: {s['blocked']}")
        print(f"  agente {s['policy_sum_r']:+.2f}R (media {s['policy_mean_r']}) | ejecutar todo "
              f"media {s['execute_all_mean_r']} | no operar 0")
        print(f"  solo explotación {s['exploit_sum_r']:+.2f}R | exploraciones media "
              f"{s['explore_mean_r']:+.2f}R")
        print(f"  MT5 real: {s['mt5_closed']} cerradas, {s['mt5_profit_usd']:+.2f} USD, "
              f"real − paper {s['mt5_minus_paper_mean_r']} (fuente única; "
              f"{s['mt5_pre_fix_paired']} previas al fix aparte)")
        for k, b in s["by_strategy"].items():
            print(f"    {k:24} n={b['n']:4} media {b['mean_r']:+.3f}R")
        if s.get("shadows"):
            print("  agentes sombra (no operan): " + " | ".join(
                f"{n} {b['sum_r']:+.2f}R (ejecutaría {int(b['executes'])})"
                for n, b in s["shadows"].items()))
    if args.evaluate:
        print("\nEvaluación v2:", json.dumps(report["evaluation_v2"], ensure_ascii=False,
                                            default=str))
        print("Evaluación de las sombras:", json.dumps(report["evaluation_shadows"],
                                                      ensure_ascii=False, default=str))
    print("\n(La t no se muestra antes de la fecha de evaluación: pre-registro v2 §3.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
