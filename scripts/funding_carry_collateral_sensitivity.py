"""Diagnóstico POST-HOC de H-FC1 (no decide; el veredicto pre-registrado es NO PASA).

Cuantifica la limitación declarada en el pre-registro: "el colateral no rinde nada".
Mejor caso: el USDT del margen (y el efectivo ocioso de V1) rinde la tasa libre de
riesgo completa (EFFR) cada 8 h. Reusa la grilla y la evaluación del estudio.
"""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import funding_carry_study as fc  # noqa: E402


def simulate_with_yield(g, start, end, variant, rf):
    fs, fp = fc.FEE_SPOT + fc.SLIP, fc.FEE_PERP + fc.SLIP
    w = g.loc[(g.index >= start) & (g.index < end)]
    rf8 = rf.reindex(w.index, method="ffill").fillna(0.0).to_numpy() / (3 * 365)
    rates = w["rate"].to_numpy()
    cash, in_pos = 1.0, False
    spot_qty = perp_qty = perp_ref = margin = last_px = 0.0
    eq = []
    for i, (T, row) in enumerate(w.iterrows()):
        S, P, H, r = row["spot"], row["perp"], row["perp_high"], row["rate"]
        if in_pos:
            margin += margin * rf8[i]                     # el margen rinde la tasa libre
            if margin + perp_qty * (perp_ref - H) <= fc.MAINT_RATIO * perp_qty * H:
                cash = spot_qty * S * (1 - fs)
                in_pos, spot_qty, perp_qty, margin = False, 0.0, 0.0, 0.0
            else:
                margin += r * perp_qty * P
                if abs(S / last_px - 1) >= fc.REBALANCE_BAND:
                    margin += perp_qty * (perp_ref - P)
                    perp_ref = P
                    equity = spot_qty * S + margin
                    n_new = equity / (1 + fc.MARGIN_RATIO)
                    fee = fs * abs(n_new - spot_qty * S) + fp * abs(n_new - perp_qty * P)
                    n_new = (equity - fee) / (1 + fc.MARGIN_RATIO)
                    spot_qty, perp_qty = n_new / S, n_new / P
                    margin, last_px = fc.MARGIN_RATIO * n_new, S
        else:
            cash += cash * rf8[i]                         # el efectivo ocioso también
        last = i == len(w) - 1
        if variant == "V0":
            want = not last
        else:
            lo = max(0, i - fc.V1_LOOKBACK + 1)
            avg = rates[lo:i + 1].mean() * 3 * 365 if i + 1 >= fc.V1_LOOKBACK else float("nan")
            want = in_pos
            if not in_pos and avg > fc.V1_ENTER:
                want = True
            elif in_pos and avg < fc.V1_EXIT:
                want = False
            if last:
                want = False
        if want and not in_pos:
            n = cash / (1 + fc.MARGIN_RATIO + fs + fp)
            spot_qty, perp_qty, perp_ref = n / S, n / P, P
            margin = cash - n - (fs + fp) * n
            cash, in_pos, last_px = 0.0, True, S
        elif in_pos and not want:
            cash = (spot_qty * S * (1 - fs) + margin + perp_qty * (perp_ref - P)
                    - perp_qty * P * fp)
            in_pos, spot_qty, perp_qty, margin = False, 0.0, 0.0, 0.0
        eq.append((T, (spot_qty * S + margin + perp_qty * (perp_ref - P)) if in_pos else cash))
    return pd.Series([e for _, e in eq], index=[t for t, _ in eq])


def main() -> int:
    data = Path(sys.argv[1])
    rf = fc.risk_free(data / "DFF.csv")
    mid = fc.DECISION_START + (fc.DECISION_END - fc.DECISION_START) / 2
    out = {}
    for sym in fc.SYMBOLS:
        g = fc.build_grid(data, sym)
        for v in ("V0", "V1"):
            curve = simulate_with_yield(g, fc.DECISION_START, fc.DECISION_END, v, rf)
            ev = fc.evaluate(curve, rf)
            h1, h2 = fc.evaluate(curve.loc[:mid], rf), fc.evaluate(curve.loc[mid:], rf)
            out[f"{sym}_{v}"] = {"cagr": ev["cagr"], "excess_ann": ev["excess_ann"],
                                 "t_weekly": ev["t_weekly"], "excess_h1": h1["excess_ann"],
                                 "excess_h2": h2["excess_ann"]}
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
