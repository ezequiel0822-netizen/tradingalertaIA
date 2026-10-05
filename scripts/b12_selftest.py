"""B12 — verificación con datos SINTÉTICOS de scripts/b12_flows_study.py (antes de bajar
datos reales). Sin red. Uso: python scripts/b12_selftest.py  (salida != 0 si falla)
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import b12_flows_study as F  # noqa: E402

DAY = pd.Timedelta(days=1)
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))


def hac_reference(y, z, L):
    n = len(y)
    X = np.column_stack([np.ones(n), z])
    b = np.linalg.solve(X.T @ X, X.T @ y)
    u = y - X @ b
    S = np.zeros((2, 2))
    for l in range(-L, L + 1):
        w = 1 - abs(l) / (L + 1)
        for t in range(n):
            s = t - l
            if 0 <= s < n:
                S += w * np.outer(X[t] * u[t], X[s] * u[s])
    A = np.linalg.inv(X.T @ X)
    V = A @ S @ A
    return b[1], b[1] / math.sqrt(V[1, 1])


def case_hac() -> None:
    rng = np.random.default_rng(3)
    z = rng.normal(size=200)
    e = np.convolve(rng.normal(size=203), [1, 0.5, 0.25, 0.1], mode="valid")
    y = 0.02 + 0.3 * z + e
    for L in (0, 4, 8):
        b, t = F.hac_slope_t(y, z, L)
        br, tr = hac_reference(y, z, L)
        check(f"1 pendiente y t HAC = referencia (L={L})", abs(b - br) < 1e-12 and abs(t - tr) < 1e-9, f"{t} vs {tr}")


def case_predictor_lags() -> None:
    days = pd.date_range("2019-01-01", "2024-10-01", freq="D", tz="UTC", unit="ns")
    stb = pd.Series(np.exp(np.linspace(0, 3, len(days))), index=days)
    T = pd.Timestamp("2022-03-07", tz="UTC")
    x0 = F.x_stb(stb, T)
    s2 = stb.copy()
    s2.loc[T - DAY] *= 10                       # domingo: todavía no publicado
    s3 = stb.copy()
    s3.loc[T - 2 * DAY] *= 10                   # sábado: sí cuenta
    exp = math.log(stb.loc[T - 2 * DAY] / stb.loc[T - 9 * DAY])
    check("2 H-STB1: ln(S[T−2d]/S[T−9d]); el dato de T−1d no se usa",
          abs(x0 - exp) < 1e-12 and F.x_stb(s2, T) == x0 and F.x_stb(s3, T) != x0)
    cm = pd.DataFrame({"FlowInExUSD": 10.0, "FlowOutExUSD": 4.0, "CapMrktCurUSD": 1000.0, "CapMVRVCur": 2.0},
                      index=days)
    cm.loc[T - DAY, "FlowInExUSD"] = 1e9         # domingo: no cuenta
    cm.loc[T - 9 * DAY, "FlowInExUSD"] = 1e9     # fuera de la ventana de 7 días
    cm.loc[T - 2 * DAY, "CapMVRVCur"] = 3.5
    check("3 H-EXF1: Σ 7 días hasta T−2d de (in − out) / cap",
          abs(F.x_exf(cm, T) - 7 * 6.0 / 1000.0) < 1e-15, str(F.x_exf(cm, T)))
    check("3 H-MVRV1: valor del día T−2d", F.x_mvrv(cm, T) == 3.5)


def case_zscore() -> None:
    idx = pd.date_range("2019-01-07", periods=120, freq="7D", tz="UTC", unit="ns")
    x = pd.Series(np.random.default_rng(1).normal(size=120), index=idx)
    z = F.zscore_weekly(x, 52, 26)
    prev = x.iloc[48:100]
    check("4 z semanal contra las 52 previas (sin la actual)", abs(z.iloc[100] - (x.iloc[100] - prev.mean()) / prev.std()) < 1e-12
          and z.iloc[:26].isna().all() and pd.notna(z.iloc[26]))


def flat_world(weekly_ret: float = 0.0):
    weeks = F.mondays(F.START - 10 * F.WEEK, F.END + 10 * F.WEEK)
    hours = pd.date_range(weeks[0], weeks[-1], freq="8h", unit="ns")
    k = np.arange(len(hours)) / 21.0
    px = {a: pd.Series(100 * (1 + weekly_ret) ** k, index=hours) for a in F.ASSETS}
    fund = {a: pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC").as_unit("ns")) for a in F.ASSETS}
    rf_w = pd.Series(0.0, index=F.mondays(F.START, F.END - F.WEEK))
    return px, fund, rf_w


def case_rule_accounting() -> None:
    px, fund, rf_w = flat_world(0.01)
    weeks = F.mondays(F.START, F.END)
    z = pd.DataFrame({"btc": 2.0, "eth": 2.0}, index=weeks)      # siempre long (H-STB1)
    ex = F.rule("H-STB1", z, px, fund, rf_w)
    c = F.FEE + F.SLIP
    check("5 regla long constante: +1 %/semana, costo al entrar y al cerrar",
          abs(ex.iloc[0] - (0.01 - c)) < 1e-12 and abs(ex.iloc[5] - 0.01) < 1e-12
          and abs(ex.iloc[-1] - (0.01 - c)) < 1e-12, str(ex.iloc[[0, 5, -1]].tolist()))
    ex_e = F.rule("H-EXF1", z, px, fund, rf_w)
    check("5 H-EXF1 con z alto -> short (−1 %/semana)", abs(ex_e.iloc[5] + 0.01) < 1e-12)
    rf2 = rf_w + 0.001
    z0 = pd.DataFrame({"btc": 0.5, "eth": np.nan}, index=weeks)
    ex0 = F.rule("H-STB1", z0, px, fund, rf2)
    check("5 sin posición: exceso 0 (el efectivo rinde la tasa libre)", (ex0 == 0).all())
    fund2 = {a: pd.Series(0.001, index=pd.date_range(F.START + pd.Timedelta(hours=8), F.END, freq="8h", unit="ns"))
             for a in F.ASSETS}
    exf = F.rule("H-STB1", z, px, fund2, rf_w)
    check("5 el long paga funding (21 liquidaciones por semana)", abs(exf.iloc[5] - (0.01 - 21 * 0.001)) < 1e-12)


def make_world(kind: str, seed: int):
    rng = np.random.default_rng(seed)
    weeks = F.mondays(F.START - 10 * F.WEEK, F.END + 10 * F.WEEK)
    zv = rng.normal(size=len(weeks))
    if kind == "drift":                              # z sube con el tiempo y el mercado también
        zv = np.linspace(-2.5, 2.5, len(weeks)) + 0.3 * rng.normal(size=len(weeks))
    r = rng.normal(0.004, 0.04, len(weeks))
    if kind == "planted":
        r += 0.03 * np.clip(zv, -2, 2)                 # z del lunes j predice el retorno j -> j+1
    if kind == "drift":
        r = rng.normal(0.01, 0.04, len(weeks))        # deriva alcista sin predicción semanal
    hours = pd.date_range(weeks[0], weeks[-1], freq="8h", unit="ns")
    wk_px = 100 * np.cumprod(np.r_[1.0, 1 + r[:-1]])
    px = {a: pd.Series(np.interp(np.arange(len(hours)) / 21.0, np.arange(len(weeks)), wk_px), index=hours)
          for a in F.ASSETS}
    for a in F.ASSETS:
        px[a].loc[weeks] = wk_px
    fund = {a: pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC").as_unit("ns")) for a in F.ASSETS}
    rf_w = pd.Series(0.0004, index=F.mondays(F.START, F.END - F.WEEK))
    z = pd.DataFrame({"btc": zv, "eth": zv}, index=weeks)
    return z.reindex(F.mondays(F.START, F.END)), px, fund, rf_w


def case_end_to_end() -> None:
    z, px, fund, rf = make_world("planted", 4)
    good = F.evaluate("H-STB1", z, px, fund, rf)
    check("6 señal sembrada -> PASA", good["pasa"], str({k: good[k] for k in ("slope", "t_nw", "rule_excess_ann")}))
    z, px, fund, rf = make_world("noise", 5)
    bad = F.evaluate("H-STB1", z, px, fund, rf)
    check("6 ruido -> NO PASA", not bad["pasa"], str({k: bad[k] for k in ("slope", "t_nw")}))
    z, px, fund, rf = make_world("drift", 6)
    dr = F.evaluate("H-STB1", z, px, fund, rf)
    check("7 'long en el bull' sin predicción semanal -> NO PASA (la pendiente no es significativa)",
          not dr["pasa"] and not dr["checks"]["1_pendiente_signo_tesis_|t_NW|>=2.50"],
          str({k: dr[k] for k in ("slope", "t_nw", "rule_excess_ann")}))
    z, px, fund, rf = make_world("planted", 4)
    neg = F.evaluate("H-EXF1", z, px, fund, rf)
    check("8 predicción con signo opuesto a la tesis -> NO PASA", not neg["pasa"]
          and not neg["checks"]["1_pendiente_signo_tesis_|t_NW|>=2.50"])
    z2 = z.copy()
    z2.iloc[::10] = np.nan
    cov = F.evaluate("H-STB1", z2, px, fund, rf)
    check("9 cobertura < 95 % -> NO PASA", not cov["checks"]["6_cobertura>=95%"])


def case_parsing() -> None:
    js = [{"date": "1577836800", "totalCirculatingUSD": {"peggedUSD": 4.0e9, "peggedEUR": 1.0e6}},
          {"date": "1577923200", "totalCirculatingUSD": {"peggedUSD": 5.0e9}}]
    d = F.parse_llama(js)
    check("10 DefiLlama: suma de pegs y fecha UTC", d["supply_usd"].tolist() == [4.001e9, 5.0e9]
          and str(d["date"].iloc[0]) == "2020-01-01 00:00:00+00:00")
    pages = [{"data": [{"asset": "btc", "time": "2020-01-01T00:00:00.000000000Z", "FlowInExUSD": "1.5",
                        "FlowOutExUSD": "1", "CapMrktCurUSD": "100", "CapMVRVCur": "2"}]},
             {"data": [{"asset": "eth", "time": "2020-01-01T00:00:00.000000000Z", "FlowInExUSD": "3",
                        "CapMrktCurUSD": "50", "CapMVRVCur": "1.5"}]}]
    c = F.parse_cm(pages)
    check("10 CoinMetrics: páginas concatenadas, texto -> número, métrica faltante -> NaN",
          len(c) == 2 and c.loc[c.asset == "btc", "FlowInExUSD"].iloc[0] == 1.5
          and np.isnan(c.loc[c.asset == "eth", "FlowOutExUSD"].iloc[0]))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for fn in (case_hac, case_predictor_lags, case_zscore, case_rule_accounting, case_end_to_end, case_parsing):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            import traceback
            check(f"{fn.__name__} EXCEPCIÓN", False, repr(e) + traceback.format_exc()[-800:])
    bad = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f"  [{detail}]" if (detail and not ok) else ""))
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} casos OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
