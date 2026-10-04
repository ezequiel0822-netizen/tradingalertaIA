"""Estudio de la tanda cripto 2026-10-04b: H-FC2, H-XS1, H-POS1.

Implementa EXACTAMENTE research/HIPOTESIS_2026-10-04b_cripto_batch.md (commiteado
antes de bajar datos). Reusa la tasa libre y la evaluación de funding_carry_study.

Uso: python scripts/crypto_batch_study.py --data <dir> --carry-data <dir H-FC1> --report <dir>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import funding_carry_study as fc  # noqa: E402

# ---- parámetros CONGELADOS por el pre-registro -----------------------------------
START = pd.Timestamp("2024-10-01", tz="UTC")
END = pd.Timestamp("2026-10-01", tz="UTC")          # exclusivo
STEP = pd.Timedelta(hours=8)
FEE_SPOT, FEE_PERP = 0.0010, 0.0005
LIQ_PERP, LIQ_SPOT = 20e6, 2e6
DELIST_PENALTY = 0.02
T_CRIT = 2.50
# H-FC2
FC2_N, FC2_MIN_APR, FC2_MARGIN, FC2_BAND, FC2_MAINT, FC2_SLIP = 5, 0.10, 1.0, 0.30, 0.01, 0.0010
FC2_MAX_DD = 0.15
# H-XS1
XS1_LOOKBACK_D, XS1_SLIP, XS1_MAX_DD = 21, 0.0005, 0.30
# H-POS1
POS_Z, POS_HOLD_D, POS_LOOKBACK_D, POS_SLIP, POS_MIN_N = 1.5, 3, 90, 0.0002, 30


# ================================ CARGA ==========================================
def load_wide(data: Path) -> dict[str, pd.DataFrame]:
    """Matrices T × símbolo. T = fin de la vela de 8 h (open_time + 8 h)."""
    def wide(kind: str, col: str) -> pd.DataFrame:
        k = pd.read_parquet(data / f"{kind}_all.parquet", columns=["symbol", "open_time", col])
        k["T"] = pd.to_datetime(k["open_time"].astype("int64"), unit="ms", utc=True) + STEP
        return k.drop_duplicates(["symbol", "T"]).pivot(index="T", columns="symbol", values=col)

    w = {"perp": wide("perp", "close"), "perp_high": wide("perp", "high"),
         "perp_qv": wide("perp", "quote_volume"), "spot": wide("spot", "close"),
         "spot_qv": wide("spot", "quote_volume")}
    fr = pd.read_parquet(data / "funding_all.parquet")
    t = pd.to_datetime(fr["calc_time"].astype("int64"), unit="ms", utc=True).dt.floor("h")
    fr["T"] = t.dt.ceil("8h")                       # eventos de 4 h → al cierre de 8 h
    fund = fr.groupby(["T", "symbol"])["funding_rate"].sum().unstack()
    grid = w["perp"].index.union(w["spot"].index).sort_values()
    for k in w:
        w[k] = w[k].reindex(grid)
    w["funding"] = fund.reindex(grid).fillna(0.0)
    return w


def daily_median_volume(qv: pd.DataFrame) -> pd.DataFrame:
    """Volumen diario (suma de las 3 velas del día UTC de inicio) y mediana de los 30
    días COMPLETOS previos a cada día (shift: nunca incluye el día en curso)."""
    day = (qv.index - STEP).floor("D")
    daily = qv.groupby(day).sum(min_count=1)
    return daily.rolling(30, min_periods=20).median().shift(1)


def at_day(daily_stat: pd.DataFrame, T: pd.Timestamp) -> pd.Series:
    d = T.floor("D")
    return daily_stat.loc[d] if d in daily_stat.index else pd.Series(dtype=float)


def first_last_valid(w: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    return w.apply(pd.Series.first_valid_index), w.apply(pd.Series.last_valid_index)


# ================================ H-FC2 ==========================================
def run_fc2(w: dict, cost_mult: float = 1.0, start=START, end=END) -> dict:
    fs = (FEE_SPOT + FC2_SLIP) * cost_mult
    fp = (FEE_PERP + FC2_SLIP) * cost_mult
    perp, high, spot, fund = w["perp"], w["perp_high"], w["spot"], w["funding"]
    both = perp.notna() & spot.notna()
    first, last = first_last_valid(perp.where(both))
    med_p, med_s = daily_median_volume(w["perp_qv"]), daily_median_volume(w["spot_qv"])
    fund7 = fund.rolling(21, min_periods=21).sum() * 365 / 7     # 21 velas de 8 h = 7 días
    grid = perp.loc[(perp.index >= start) & (perp.index < end)].index
    cash, pos, curve = 1.0, {}, []
    st = {"entries": 0, "exits": 0, "liquidations": 0, "delistings": 0,
          "entry_apr": [], "held_funding": [], "n_positions": []}

    def pos_equity(p: dict) -> float:
        return p["spot_qty"] * p["S"] + p["margin"] + p["perp_qty"] * (p["ref"] - p["P"])

    def close(sym: str, S: float, P: float, penalty: float = 0.0) -> float:
        p = pos.pop(sym)
        st["exits"] += 1
        notional = p["spot_qty"] * S
        return (notional * (1 - fs) + p["margin"] + p["perp_qty"] * (p["ref"] - P)
                - p["perp_qty"] * P * fp - penalty * notional)

    for T in grid:
        for sym in list(pos):
            p = pos[sym]
            if T > last[sym]:                        # deslistado: sale al último dato
                Tl = last[sym]
                cash += close(sym, spot.at[Tl, sym], perp.at[Tl, sym], DELIST_PENALTY)
                st["delistings"] += 1
                continue
            S, P, H = spot.at[T, sym], perp.at[T, sym], high.at[T, sym]
            if np.isnan(S) or np.isnan(P):
                continue                             # hueco puntual: no se actualiza
            p["S"], p["P"] = S, P
            if p["margin"] + p["perp_qty"] * (p["ref"] - H) <= FC2_MAINT * p["perp_qty"] * H:
                st["liquidations"] += 1
                pos.pop(sym)
                cash += p["spot_qty"] * S * (1 - fs)
                continue
            r = fund.at[T, sym]
            p["margin"] += r * p["perp_qty"] * P
            p["funding_acc"] += r
            if abs(S / p["last_px"] - 1) >= FC2_BAND:
                p["margin"] += p["perp_qty"] * (p["ref"] - P)
                p["ref"] = P
                eq = p["spot_qty"] * S + p["margin"]
                n_new = eq / (1 + FC2_MARGIN)
                fee = fs * abs(n_new - p["spot_qty"] * S) + fp * abs(n_new - p["perp_qty"] * P)
                n_new = (eq - fee) / (1 + FC2_MARGIN)
                p.update(spot_qty=n_new / S, perp_qty=n_new / P, margin=FC2_MARGIN * n_new,
                         last_px=S)
        if T.weekday() == 0 and T.hour == 0:         # rebalanceo semanal lunes 00:00
            elig = [s for s in perp.columns
                    if s not in ("BTCUSDT", "ETHUSDT") and both.at[T, s]
                    and pd.notna(first[s]) and first[s] <= T - pd.Timedelta(days=30)]
            mp, ms = at_day(med_p, T), at_day(med_s, T)
            elig = [s for s in elig if mp.get(s, 0) >= LIQ_PERP and ms.get(s, 0) >= LIQ_SPOT]
            score = fund7.loc[T, elig].dropna().sort_values(ascending=False)
            chosen = list(score[score >= FC2_MIN_APR].index[:FC2_N])
            for sym in list(pos):
                if sym not in chosen:
                    p = pos[sym]
                    st["held_funding"].append(p["funding_acc"] / max(p["bars"], 1) * 3 * 365)
                    cash += close(sym, p["S"], p["P"])
            equity = cash + sum(pos_equity(p) for p in pos.values())
            new = [s for s in chosen if s not in pos]
            cap = min(equity / FC2_N, cash / len(new)) if new else 0.0   # mismo monto a cada nueva
            for sym in new:
                S, P = spot.at[T, sym], perp.at[T, sym]
                n = cap / (1 + FC2_MARGIN + fs + fp)
                pos[sym] = {"spot_qty": n / S, "perp_qty": n / P, "ref": P,
                            "margin": cap - n - (fs + fp) * n, "last_px": S,
                            "funding_acc": 0.0, "bars": 0, "S": S, "P": P}
                cash -= cap
                st["entries"] += 1
                st["entry_apr"].append(float(score[sym]))
            st["n_positions"].append(len(pos))
        for p in pos.values():
            p["bars"] += 1
        eq = cash + sum(pos_equity(p) for p in pos.values())
        curve.append((T, eq))
    for sym in list(pos):                            # cierre al final de la ventana
        cash += close(sym, pos[sym]["S"], pos[sym]["P"])
    curve[-1] = (curve[-1][0], cash)
    st["curve"] = pd.Series([e for _, e in curve], index=[t for t, _ in curve])
    return st


# ================================ H-XS1 ==========================================
def run_xs1(w: dict, cost_mult: float = 1.0, start=START, end=END) -> dict:
    cost = (FEE_PERP + XS1_SLIP) * cost_mult
    perp, fund = w["perp"], w["funding"]
    _, last = first_last_valid(perp)
    med_p = daily_median_volume(w["perp_qv"])
    lb = XS1_LOOKBACK_D * 3
    grid = perp.loc[(perp.index >= start) & (perp.index < end)].index
    eq, qty, prev_px, curve = 1.0, {}, {}, []
    st = {"rebalances": 0, "delistings": 0, "n_side": [], "turnover": []}
    for T in grid:
        for sym in list(qty):
            if T > last[sym]:
                Pl = perp.at[last[sym], sym]
                eq += qty[sym] * (Pl - prev_px[sym]) - DELIST_PENALTY * abs(qty[sym] * Pl)
                eq -= cost * abs(qty[sym] * Pl)
                qty.pop(sym), prev_px.pop(sym)
                st["delistings"] += 1
                continue
            P = perp.at[T, sym]
            if np.isnan(P):
                continue
            eq += qty[sym] * (P - prev_px[sym]) - qty[sym] * P * fund.at[T, sym]
            prev_px[sym] = P
        if T.weekday() == 0 and T.hour == 0:
            i = perp.index.get_loc(T)
            if i >= lb:
                past = perp.iloc[i - lb]
                mp = at_day(med_p, T)
                cand = [s for s in perp.columns
                        if pd.notna(perp.at[T, s]) and pd.notna(past[s]) and mp.get(s, 0) >= LIQ_PERP]
                ret = (perp.loc[T, cand] / past[cand] - 1).sort_values()
                q = len(ret) // 5
                target = {}
                if q >= 1:
                    for s in ret.index[-q:]:
                        target[s] = 0.5 * eq / q / perp.at[T, s]
                    for s in ret.index[:q]:
                        target[s] = -0.5 * eq / q / perp.at[T, s]
                turnover = 0.0
                for s in set(qty) | set(target):
                    P = perp.at[T, s]
                    if np.isnan(P):
                        P = prev_px[s]               # hueco puntual: último precio válido
                    turnover += abs(target.get(s, 0.0) - qty.get(s, 0.0)) * P
                eq -= cost * turnover
                qty = {s: v for s, v in target.items()}
                prev_px = {s: perp.at[T, s] for s in qty}
                st["rebalances"] += 1
                st["n_side"].append(q)
                st["turnover"].append(turnover / max(eq, 1e-12))
        curve.append((T, eq))
    eq -= cost * sum(abs(v * prev_px[s]) for s, v in qty.items())   # cierre final
    curve[-1] = (curve[-1][0], eq)
    st["curve"] = pd.Series([e for _, e in curve], index=[t for t, _ in curve])
    return st


# ================================ H-POS1 =========================================
def daily_ratio(metrics: pd.DataFrame) -> pd.Series:
    m = metrics.copy()
    m["ts"] = pd.to_datetime(m["create_time"], utc=True)
    m = m.sort_values("ts")
    m["day"] = (m["ts"] - pd.Timedelta(seconds=1)).dt.floor("D")   # 00:00 cierra el día previo
    return m.groupby("day")["count_long_short_ratio"].last().astype(float)


def run_pos1(w: dict, metrics: dict[str, pd.DataFrame], cost_mult: float = 1.0,
             rf: pd.Series | None = None, start=START, end=END) -> pd.DataFrame:
    cost = 2 * (FEE_PERP + POS_SLIP) * cost_mult
    rows = []
    for sym, met in metrics.items():
        v = daily_ratio(met)
        prev = v.shift(1).rolling(POS_LOOKBACK_D, min_periods=60)
        z = (v - prev.mean()) / prev.std()
        perp, fund = w["perp"][sym], w["funding"][sym]
        free_at = start
        for d, zd in z.items():
            T_in = d + pd.Timedelta(days=1)           # cierre del día d = 00:00 UTC de d+1
            if T_in < max(start, free_at) or T_in >= end or np.isnan(zd) or abs(zd) <= POS_Z:
                continue
            T_out = T_in + pd.Timedelta(days=POS_HOLD_D)
            if T_out > end or T_in not in perp.index or T_out not in perp.index:
                continue
            p_in, p_out = perp.at[T_in], perp.at[T_out]
            if np.isnan(p_in) or np.isnan(p_out):
                continue
            side = -1.0 if zd > POS_Z else 1.0
            held = fund.loc[(fund.index > T_in) & (fund.index <= T_out)].sum()
            ret = side * (p_out / p_in - 1) - side * held - cost
            rfr = 0.0
            if rf is not None:
                r = rf.reindex([T_in], method="ffill").iloc[0]
                rfr = (1 + (0.0 if np.isnan(r) else r)) ** (POS_HOLD_D / 365) - 1
            rows.append({"symbol": sym, "entry": T_in, "side": side, "z": float(zd),
                         "ret": ret, "excess": ret - rfr})
            free_at = T_out
    return pd.DataFrame(rows)


def pos_stats(trades: pd.DataFrame, mid: pd.Timestamp) -> dict:
    n = len(trades)
    if n < 2:
        return {"n": n, "mean_excess": None, "t": None, "h1": None, "h2": None}
    x = trades["excess"]
    t = float(x.mean() / (x.std(ddof=1) / np.sqrt(n))) if x.std() > 0 else None
    h1 = trades.loc[trades["entry"] < mid, "excess"]
    h2 = trades.loc[trades["entry"] >= mid, "excess"]
    return {"n": n, "mean_excess": float(x.mean()), "t": t,
            "h1": float(h1.mean()) if len(h1) else None,
            "h2": float(h2.mean()) if len(h2) else None,
            "win": float((x > 0).mean()),
            "longs": int((trades["side"] > 0).sum()), "shorts": int((trades["side"] < 0).sum())}


# ================================ MAIN ===========================================
def gate_curve(curve: pd.Series, curve_x2: pd.Series, rf: pd.Series, max_dd: float) -> dict:
    mid = START + (END - START) / 2
    ev = fc.evaluate(curve, rf)
    h1, h2 = fc.evaluate(curve.loc[:mid], rf), fc.evaluate(curve.loc[mid:], rf)
    x2 = fc.evaluate(curve_x2, rf)
    checks = {"excess_pos": ev["excess_ann"] > 0,
              "t_ok": ev["t_weekly"] is not None and ev["t_weekly"] >= T_CRIT,
              "dd_ok": ev["max_dd"] >= -max_dd,
              "halves_pos": h1["excess_ann"] > 0 and h2["excess_ann"] > 0,
              "cost_x2_pos": x2["excess_ann"] > 0}
    return {**ev, "excess_h1": h1["excess_ann"], "excess_h2": h2["excess_ann"],
            "excess_cost_x2": x2["excess_ann"], "checks": checks, "passes": all(checks.values())}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--carry-data", required=True)
    ap.add_argument("--report", required=True)
    a = ap.parse_args()
    data, report = Path(a.data), Path(a.report)
    report.mkdir(parents=True, exist_ok=True)
    rf = fc.risk_free(Path(a.carry_data) / "DFF.csv")
    fc.log("cargando matrices...")
    w = load_wide(data)
    res: dict = {}

    fc.log("H-FC2...")
    r1, r2 = run_fc2(w), run_fc2(w, cost_mult=2.0)
    g = gate_curve(r1["curve"], r2["curve"], rf, FC2_MAX_DD)
    res["H-FC2"] = {**g, "entries": r1["entries"], "exits": r1["exits"],
                    "liquidations": r1["liquidations"], "delistings": r1["delistings"],
                    "mean_positions": float(np.mean(r1["n_positions"])) if r1["n_positions"] else 0,
                    "entry_apr_median": float(np.median(r1["entry_apr"])) if r1["entry_apr"] else None,
                    "held_funding_apr_median": float(np.median(r1["held_funding"])) if r1["held_funding"] else None}
    fc.log(f"  H-FC2 exceso {g['excess_ann']:+.2%} t={g['t_weekly']} -> {'PASA' if g['passes'] else 'NO PASA'}")

    fc.log("H-XS1...")
    x1, x2 = run_xs1(w), run_xs1(w, cost_mult=2.0)
    g = gate_curve(x1["curve"], x2["curve"], rf, XS1_MAX_DD)
    res["H-XS1"] = {**g, "rebalances": x1["rebalances"], "delistings": x1["delistings"],
                    "median_per_side": float(np.median(x1["n_side"])) if x1["n_side"] else 0,
                    "median_weekly_turnover": float(np.median(x1["turnover"])) if x1["turnover"] else 0}
    fc.log(f"  H-XS1 exceso {g['excess_ann']:+.2%} t={g['t_weekly']} -> {'PASA' if g['passes'] else 'NO PASA'}")

    fc.log("H-POS1...")
    mets = {s: pd.read_parquet(data / f"metrics_{s}.parquet") for s in ("BTCUSDT", "ETHUSDT")}
    mid = START + (END - START) / 2
    t1 = run_pos1(w, mets, rf=rf)
    t2 = run_pos1(w, mets, cost_mult=2.0, rf=rf)
    s1, s2 = pos_stats(t1, mid), pos_stats(t2, mid)
    checks = {"excess_pos": (s1["mean_excess"] or -1) > 0,
              "t_ok": s1["t"] is not None and s1["t"] >= T_CRIT,
              "n_ok": s1["n"] >= POS_MIN_N,
              "halves_pos": (s1["h1"] or -1) > 0 and (s1["h2"] or -1) > 0,
              "cost_x2_pos": (s2["mean_excess"] or -1) > 0}
    res["H-POS1"] = {**s1, "mean_excess_cost_x2": s2["mean_excess"], "checks": checks,
                     "passes": all(checks.values())}
    fc.log(f"  H-POS1 n={s1['n']} exceso/trade {s1['mean_excess']} t={s1['t']} -> "
           f"{'PASA' if res['H-POS1']['passes'] else 'NO PASA'}")
    t1.to_csv(report / "pos1_trades.csv", index=False)
    (report / "results.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    print(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
