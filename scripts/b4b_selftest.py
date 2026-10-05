"""B4b — verificación con datos SINTÉTICOS de scripts/b4b_study.py y del almacén de
scripts/b4b_forward_collector.py (pre-registro §8: antes de bajar la secundaria).

Cada caso tiene un resultado conocido en forma cerrada o una propiedad que no puede
fallar si la contabilidad es correcta. No usa red ni datos reales.

Uso: python scripts/b4b_selftest.py      (salida != 0 si algún caso falla)
"""

from __future__ import annotations

import math
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import b4b_forward_collector as C  # noqa: E402
import b4b_study as S  # noqa: E402

H = pd.Timedelta(hours=1)
START = pd.Timestamp("2030-01-07 00:00", tz="UTC")     # lunes cualquiera, fuera de toda ventana
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))


def grid_from(hl_c, bn_c=None, start=START, hl_h=None, bn_l=None) -> pd.DataFrame:
    hl_c = np.asarray(hl_c, float)
    bn_c = hl_c.copy() if bn_c is None else np.asarray(bn_c, float)
    n = len(hl_c)
    idx = pd.date_range(start, periods=n, freq="h", unit="ns")
    hl_o = np.r_[hl_c[0], hl_c[:-1]]
    bn_o = np.r_[bn_c[0], bn_c[:-1]]
    g = pd.DataFrame({"hl_o": hl_o, "hl_h": np.maximum(hl_o, hl_c), "hl_l": np.minimum(hl_o, hl_c),
                      "hl_c": hl_c, "bn_o": bn_o, "bn_h": np.maximum(bn_o, bn_c),
                      "bn_l": np.minimum(bn_o, bn_c), "bn_c": bn_c}, index=idx)
    if hl_h is not None:
        for k, v in hl_h.items():
            g.iloc[k, g.columns.get_loc("hl_h")] = v
    if bn_l is not None:
        for k, v in bn_l.items():
            g.iloc[k, g.columns.get_loc("bn_l")] = v
    return g


def hourly_funding(start, n, rate, extra=None) -> pd.Series:
    idx = pd.date_range(start + H, periods=n, freq="h", unit="ns")
    s = pd.Series(rate, index=idx, dtype=float)
    if extra:
        for t, v in extra.items():
            s.loc[t] = v
    return s.sort_index()


def eight_h_funding(start, end, rate, extra=None) -> pd.Series:
    idx = pd.date_range(start + pd.Timedelta(hours=8), end, freq="8h", unit="ns")
    s = pd.Series(rate, index=idx, dtype=float)
    if extra:
        for t, v in extra.items():
            s.loc[t] = v
    return s.sort_index()


EMPTY = pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC").as_unit("ns"))
C_HL = S.FEE_HL + S.SLIP
C_BN = S.FEE_BN + S.SLIP


def case_closed_form() -> None:
    n = 14 * 24
    end = START + n * H
    g = grid_from(np.full(n, 100.0))
    fh, fb = 0.0000125, 0.00005
    # funding gigante EN τ = apertura: no debe contar (apertura < τ <= cierre)
    f_hl = hourly_funding(START, n, fh, {START: 0.5})
    f_bn = eight_h_funding(START, end, fb, {START: 0.5})
    r = S.simulate(g, f_hl, f_bn, "BTC")
    exp = 1 - 2 * 1.5 * (C_HL + C_BN) + 1.5 * (n * fh - 42 * fb)
    got = float(r["curve"].iloc[-1])
    check("A forma cerrada (precio fijo, funding constante, bordes)", abs(got - exp) < 1e-12,
          f"got {got:.15f} exp {exp:.15f}")
    check("A sin rebalanceos ni liquidaciones", not r["rebalances"] and not r["liquidations"])
    check("A funding en τ = cierre SÍ cuenta (336 HL / 42 BN)",
          abs(r["funding_hl_received"] - 1.5 * n * fh) < 1e-12
          and abs(r["funding_bn_paid"] - 1.5 * 42 * fb) < 1e-12)
    r2 = S.simulate(g, f_hl, f_bn, "BTC", cost_mult=2.0)
    check("B costos x2 duplican exactamente el costo de operar",
          abs(r2["cost_trading"] - 2 * r["cost_trading"]) < 1e-15)
    check("B curva arranca en 1.0 y tiene n+1 puntos",
          r["curve"].iloc[0] == 1.0 and len(r["curve"]) == n + 1 and r["curve"].index[-1] == end)


def case_delta_neutral() -> None:
    rng = np.random.default_rng(7)
    n = 500
    p = 100 * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    p = np.clip(p, 95, 105)
    g = grid_from(p)
    r = S.simulate(g, EMPTY, EMPTY, "ETH", cost_mult=0.0)
    dev = float(np.abs(r["curve"].to_numpy() - 1.0).max())
    check("C delta neutral: mismo precio en ambos venues -> equity constante", dev < 1e-12, f"dev {dev:.2e}")


def case_price_gap() -> None:
    n = 48
    bn = np.full(n, 100.0)
    hl = bn.copy()
    hl[-1] = 100.1                              # HL cierra 0.1 % arriba de Binance
    g = grid_from(hl, bn)
    r = S.simulate(g, EMPTY, EMPTY, "BTC", cost_mult=0.0)
    q = 1.5 / 100
    exp = 1 - q * (100.1 - 100.0)
    check("D brecha HL−Binance entra al PnL (short pierde si HL sube)",
          abs(float(r["curve"].iloc[-1]) - exp) < 1e-12)


def ratio_trigger_hour(p: np.ndarray, q: float, c0: float) -> int:
    """Hora (índice de vela) del primer cierre con ratio de la pata HL < 0.20 (sin funding)."""
    for k, pk in enumerate(p):
        e_hl = 0.5 - c0 - q * (pk - p[0])
        if e_hl / (q * pk) < S.REB_TRIGGER:
            return k
    return -1


def case_rebalance() -> None:
    ramp = np.r_[np.full(5, 100.0), np.linspace(101, 113, 13), np.full(60, 113.0)]
    g = grid_from(ramp)
    q = 1.5 / 100
    k = ratio_trigger_hour(ramp, q, 0.0)
    r = S.simulate(g, EMPTY, EMPTY, "BTC", cost_mult=0.0)
    exp_time = str(g.index[k] + H + S.REB_DELAY)
    ok = len(r["rebalances"]) == 1 and r["rebalances"][0]["time"] == exp_time
    check("E gatillo al primer cierre con ratio < 0.20 y ejecución 24 h después", ok,
          f"{r['rebalances'][:1]} esperado {exp_time}")
    if r["rebalances"]:
        qn = r["rebalances"][0]["q_new"]
        check("E re-dimensiona a N' = 1.5 x E (sin costos: q' = 1.5/113)", abs(qn - 1.5 / 113) < 1e-14)
        check("E sin costos la equity sigue en 1.0", abs(float(r["curve"].iloc[-1]) - 1.0) < 1e-12)
    rc = S.simulate(g, EMPTY, EMPTY, "BTC", cost_mult=1.0)
    k1 = ratio_trigger_hour(ramp, q, C_HL * q * 100)
    x_exp = 0.5 - C_HL * 1.5 - q * (113 - 100) - (1 - 1.5 * (C_HL + C_BN)) / 2
    x_got = rc["rebalances"][0]["transfer"] if rc["rebalances"] else float("nan")
    check("E con costos: monto transferido y costo de transferencia",
          abs(x_got - abs(x_exp)) < 1e-12
          and abs(rc["cost_transfer"] - (S.XFER_PCT * abs(x_exp) + S.XFER_FIX)) < 1e-15
          and k1 == k, f"X {x_got} vs {abs(x_exp)}")


def case_liquidations() -> None:
    n = 40
    p = np.full(n, 100.0)
    p[10:] = 101.0
    f = hourly_funding(START, n, 0.001)
    g = grid_from(p, hl_h={10: 140.0})
    r = S.simulate(g, f, EMPTY, "BTC")
    q = 1.5 / 100
    e_bn = 0.5 - C_BN * q * 100 + q * (101 - 100) - C_BN * q * 101
    tail = r["curve"].iloc[11:].to_numpy()
    check("F liquidación de la pata HL con el máximo intra-vela",
          len(r["liquidations"]) == 1 and r["liquidations"][0]["legs"].strip() == "HL",
          str(r["liquidations"]))
    check("F tras liquidar: equity = pata Binance cerrada con costos, plana, sin funding",
          abs(tail[0] - e_bn) < 1e-12 and np.all(tail == tail[0]), f"{tail[0]} vs {e_bn}")

    ramp = np.r_[np.full(5, 100.0), np.linspace(101, 112, 12), np.full(40, 112.0)]
    k = ratio_trigger_hour(ramp, q, C_HL * q * 100)
    g2 = grid_from(ramp, hl_h={k + 12: 112 * 1.25})
    r2 = S.simulate(g2, EMPTY, EMPTY, "BTC")
    check("G liquidación DURANTE la demora de 24 h (antes del rebalanceo)",
          len(r2["liquidations"]) == 1 and not r2["rebalances"])

    g3 = grid_from(np.full(n, 100.0), bn_l={20: 60.0})
    r3 = S.simulate(g3, EMPTY, EMPTY, "ETH")
    check("H liquidación de la pata Binance con el mínimo intra-vela",
          len(r3["liquidations"]) == 1 and r3["liquidations"][0]["legs"] == "BN")

    g4 = grid_from(np.full(n, 100.0), hl_h={20: 125.0})
    r4 = S.simulate(g4, EMPTY, EMPTY, "ETH")
    check("I mecha a +25 % NO liquida a 3x (MM ETH 2 %)", not r4["liquidations"])


def nw_reference(x: np.ndarray, lags: int) -> float:
    n = len(x)
    m = x.mean()
    def gamma(l):  # noqa: E306
        return sum((x[t] - m) * (x[t - l] - m) for t in range(l, n)) / n
    lrv = gamma(0) + 2 * sum((1 - l / (lags + 1)) * gamma(l) for l in range(1, lags + 1))
    return m / math.sqrt(lrv / n)


def case_newey_west() -> None:
    rng = np.random.default_rng(11)
    e = rng.normal(0.001, 0.002, 60)
    x = np.convolve(e, [1, 0.6, 0.3], mode="valid")       # autocorrelado
    got, ref = S.nw_t(x), nw_reference(x, 4)
    check("J Newey-West = implementación de referencia (Bartlett, 4 rezagos)", abs(got - ref) < 1e-10,
          f"{got} vs {ref}")
    n = len(x)
    t0 = S.nw_t(x, lags=0)
    ts = x.mean() / (x.std(ddof=1) / math.sqrt(n))
    check("J con 0 rezagos coincide con la t simple (corrección n/(n−1))",
          abs(t0 - ts * math.sqrt(n / (n - 1))) < 1e-10)
    check("J autocorrelación positiva -> |t_NW| < |t simple|", abs(got) < abs(ts))


def case_evaluate() -> None:
    effr_days = pd.date_range(S.T0 - pd.Timedelta(days=20), S.T1, freq="B", unit="ns")
    effr = pd.Series(0.036, index=effr_days)
    sat = pd.Timestamp("2026-10-10", tz="UTC")           # sábado
    d = S.effr_daily(effr, S.T0, S.T1)
    check("L EFFR as-of: el sábado usa el viernes", d.loc[sat] == 0.036 and len(d) == 182)
    bounds = pd.date_range(S.T0, S.T1, freq="7D", unit="ns")
    rf_w = (1 + 0.036 / 360) ** 7 - 1
    vals = [1.0]
    for j in range(26):
        vals.append(vals[-1] * (1 + rf_w + (0.001 if j < 13 else -0.0005)))
    curve = pd.Series(vals, index=bounds)
    ev = S.evaluate(curve, effr, S.T0, S.T1)
    check("K 26 semanas exactas en T0 -> T1", ev["weeks"] == 26)
    check("K exceso anual y mitades exactos",
          abs(ev["excess_ann"] - 0.013) < 1e-12 and abs(ev["excess_half1_ann"] - 0.052) < 1e-12
          and abs(ev["excess_half2_ann"] + 0.026) < 1e-12, str({k: ev[k] for k in ("excess_ann", "excess_half1_ann", "excess_half2_ann")}))
    try:
        S.evaluate(curve, effr, S.T0, S.T1 - pd.Timedelta(days=1))
        check("K ventana no entera en semanas -> error", False)
    except ValueError:
        check("K ventana no entera en semanas -> error", True)


def case_quality() -> None:
    n = 1000
    end = START + n * H
    idx = pd.date_range(START, periods=n, freq="h", unit="ns")
    px = pd.DataFrame({"o": 100.0, "h": 101.0, "l": 99.0, "c": np.linspace(100, 110, n)}, index=idx)
    drop = px.drop(idx[100:120])                           # 2 % faltante
    g, gq = S.build_grid(START, end, drop, None)
    fq = S.funding_quality(hourly_funding(START, n, 1e-5), eight_h_funding(START, end, 1e-4), START, end)
    q = S.quality_verdict(gq, fq)
    filled = g.iloc[100]
    prev_c = px["c"].iloc[99]
    check("M vela faltante = cierre anterior (o=h=l=c)",
          all(abs(filled[c] - prev_c) < 1e-12 for c in ("bn_o", "bn_h", "bn_l", "bn_c")))
    check("M 2 % de velas faltantes -> ventana INVÁLIDA", gq["missing_bn_bars"] == 20 and not q["valid"])
    g2, gq2 = S.build_grid(START, end, px.drop(idx[100:105]), None)
    check("M 0.5 % faltante -> válida", S.quality_verdict(gq2, fq)["valid"])
    fh = hourly_funding(START, n, 1e-5).drop(pd.date_range(START + 51 * H, periods=20, freq="h", unit="ns"))
    fq3 = S.funding_quality(fh, eight_h_funding(START, end, 1e-4), START, end)
    check("M 2 % de funding HL faltante -> INVÁLIDA",
          fq3["missing_hl_funding"] == 20 and not S.quality_verdict(gq2, fq3)["valid"])
    fb = eight_h_funding(START, end, 1e-4)
    fq4 = S.funding_quality(hourly_funding(START, n, 1e-5), fb.drop(fb.index[5:7]), START, end)
    check("M 2 liquidaciones de Binance faltantes de 125 -> INVÁLIDA",
          fq4["missing_bn_funding"] == 2 and fq4["expected_bn_funding"] == 125
          and not S.quality_verdict(gq2, fq4)["valid"])


def case_parsing() -> None:
    df = pd.DataFrame({"time_ms": [1696118400074, 1696122000003, 1696122000500],
                       "fundingRate": ["0.0000125", "0.00001", "0.00002"]})
    s, dup = S.funding_series(df)
    check("N funding redondeado a la hora y duplicados sumados",
          len(s) == 2 and dup == 1 and abs(s.iloc[1] - 0.00003) < 1e-15
          and s.index[0] == pd.Timestamp("2023-10-01 00:00", tz="UTC"))
    rows = [[1696118400000, "1", "2", "0.5", "1.5", "9"], [1696122000000, "1.5", "2", "1", "1.2", "9"]]
    no_head = pd.DataFrame(rows)
    head = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close", "volume"])
    micro = pd.DataFrame([[r[0] * 1000] + r[1:] for r in rows])
    a, b, c = S.norm_klines(no_head), S.norm_klines(head), S.norm_klines(micro)
    check("Q klines con/sin encabezado y en µs normalizan igual", a.equals(b) and a.equals(c))
    s0 = S.align_start(pd.Timestamp("2023-05-12", tz="UTC"), S.S1)
    check("O S0 alineado: S1 − S0 múltiplo de 7 días y corrimiento < 7 días",
          (S.S1 - s0) % pd.Timedelta(days=7) == pd.Timedelta(0)
          and pd.Timedelta(0) <= s0 - pd.Timestamp("2023-05-12", tz="UTC") < pd.Timedelta(days=7))


def case_guard() -> None:
    try:
        S.assert_forward_allowed(S.T1 + pd.Timedelta(hours=23))
        ok = False
    except SystemExit:
        ok = True
    try:
        S.assert_forward_allowed(S.T1 + pd.Timedelta(days=1))
        ok2 = True
    except SystemExit:
        ok2 = False
    try:
        S.forward(Path("no-existe"), Path("no-existe"), Path("no-existe"), now=S.T0)
        ok3 = False
    except SystemExit:
        ok3 = True
    check("P guard: la decisoria NO se evalúa antes de T1 + 1 día (ni toca la red)", ok and ok2 and ok3)
    check("P fechas congeladas: T0 2026-10-06, T1 2027-04-06",
          str(S.T0) == "2026-10-06 00:00:00+00:00" and str(S.T1) == "2027-04-06 00:00:00+00:00"
          and C.T0_MS == S.ms(S.T0) and C.T1_MS == S.ms(S.T1))


def case_end_to_end() -> None:
    rng = np.random.default_rng(3)
    n = 182 * 24
    p = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    g = grid_from(p, start=S.T0)
    effr = pd.Series(0.036, index=pd.date_range(S.T0 - pd.Timedelta(days=20), S.T1, freq="D", unit="ns"))
    good_h = hourly_funding(S.T0, n, 0.0000125) + rng.normal(0, 2e-6, n)
    bn = eight_h_funding(S.T0, S.T1, 0.00002)
    bn = bn + rng.normal(0, 1e-5, len(bn))
    q = S.quality_verdict(S.build_grid(S.T0, S.T1, g[["bn_o", "bn_h", "bn_l", "bn_c"]].set_axis(["o", "h", "l", "c"], axis=1), None)[1],
                          S.funding_quality(good_h, bn, S.T0, S.T1))
    good = S.run_window("BTC", g, good_h, bn, effr, S.T0, S.T1, 0.0, q)
    bad_h = hourly_funding(S.T0, n, 0.000002) + rng.normal(0, 2e-6, n)
    bad = S.run_window("BTC", g, bad_h, bn, effr, S.T0, S.T1, 0.0, q)
    check("R spread sintético fuerte (~10 % bruto) PASA", good["pasa"], str(good["checks"]))
    check("R spread sintético negativo NO PASA", not bad["pasa"] and not bad["checks"]["1_exceso_neto>0"])


def case_collector_store() -> None:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td)
        base = C.COLLECT_FROM_MS
        rows = [{"time_ms": str(base + k * C.H_MS + 74), "fundingRate": "0.0000125", "premium": "0"}
                for k in range(1, 101) if k not in (20, 21)]
        a1, c1 = C.merge(out, "hl_funding_BTC", rows, "run1")
        a2, c2 = C.merge(out, "hl_funding_BTC", rows, "run2")
        changed = [dict(rows[0], fundingRate="0.0000999")]
        a3, c3 = C.merge(out, "hl_funding_BTC", changed, "run3")
        store = C.read_store(out / "data" / "hl_funding_BTC.csv", "time_ms")
        conflicts = (out / "conflicts.csv").read_text(encoding="utf-8").strip().splitlines()
        check("S colector idempotente y registra valores que cambian",
              (a1, c1, a2, c2, a3, c3) == (98, 0, 0, 0, 0, 1) and len(conflicts) == 2
              and store[int(rows[0]["time_ms"])]["fundingRate"] == "0.0000999")
        now = base + 100 * C.H_MS + 1000
        h = C.health("hl_funding_BTC", store, now)
        check("S salud: cuenta 2 horas faltantes y arranca la próxima corrida desde el hueco",
              h["missing"] == 2 and h["expected"] == 100
              and C.start_for("hl_funding_BTC", store, now) == base + 20 * C.H_MS)
        full = {k: v for k, v in store.items()}
        for k in (20, 21):
            full[base + k * C.H_MS + 74] = dict(rows[0])
        check("S sin huecos: la corrida arranca 48 h antes del último dato",
              C.start_for("hl_funding_BTC", full, now) == max(full) - C.OVERLAP_MS)


def case_forward_plumbing() -> None:
    """forward() de punta a punta con la red simulada: debe dar EXACTAMENTE lo mismo que
    run_window sobre la verdad sintética, usar REST cuando falta el mensual de abril,
    detectar un funding alterado en el colector y usar la versión re-bajada."""
    rng = np.random.default_rng(5)
    lo, hi = S.T0 - pd.Timedelta(hours=48), S.T1 + pd.Timedelta(hours=24)
    bars = pd.date_range(lo, hi - H, freq="h", unit="ns")
    truth = {}
    for coin, sym in S.COINS.items():
        bn_c = 100 * np.exp(np.cumsum(rng.normal(0, 0.003, len(bars))))
        hl_c = bn_c * (1 + rng.normal(0, 0.0002, len(bars)))
        def ohlc(c):  # noqa: E306
            o = np.r_[c[0], c[:-1]]
            return pd.DataFrame({"o": o, "h": np.maximum(o, c) * 1.001, "l": np.minimum(o, c) * 0.999, "c": c},
                                index=bars)
        f_tau = pd.date_range(lo + H, hi, freq="h", unit="ns")
        b_tau = pd.date_range(lo + pd.Timedelta(hours=8), hi, freq="8h", unit="ns")
        truth[coin] = {"hl": ohlc(hl_c), "bn": ohlc(bn_c),
                       "fh": pd.Series(0.0000125 + rng.normal(0, 3e-6, len(f_tau)), index=f_tau),
                       "fb": pd.Series(0.00004 + rng.normal(0, 2e-5, len(b_tau)), index=b_tau)}
    tms = lambda ts: int(ts.timestamp() * 1000)  # noqa: E731
    with tempfile.TemporaryDirectory() as td:
        col = Path(td) / "collector" / "data"
        col.mkdir(parents=True)
        for coin, sym in S.COINS.items():
            t = truth[coin]
            fh = pd.DataFrame({"time_ms": [tms(x) + 74 for x in t["fh"].index],
                               "fundingRate": [repr(v) for v in t["fh"]], "premium": "0"})
            fh.loc[100, "fundingRate"] = "0.5"                      # valor alterado en el colector
            fh.to_csv(col / f"hl_funding_{coin}.csv", index=False)
            hc = pd.DataFrame({"t_ms": [tms(x) for x in bars], "T_ms": [tms(x) + 3599999 for x in bars],
                               **{k: [repr(v) for v in t["hl"][k]] for k in "ohlc"}, "v": "1", "n": "1"})
            hc.to_csv(col / f"hl_candles_1h_{coin}.csv", index=False)
            pd.DataFrame({"time_ms": [tms(x) + 2 for x in t["fb"].index], "fundingRate": t["fb"].to_numpy(),
                          "markPrice": 1.0}).to_csv(col / f"bn_funding_{sym}.csv", index=False)
            pd.DataFrame({"open_time_ms": [tms(x) for x in bars], **{k: t["bn"][k].to_numpy() for k in "ohlc"},
                          "v": 1.0, "close_time_ms": [tms(x) + 3599999 for x in bars]}
                         ).to_csv(col / f"bn_klines_1h_{sym}.csv", index=False)

        def fake_hl_paged(kind, coin, start, end, manifest, raw_dir):
            t = truth[coin]
            if kind == "funding":
                return [{"time": tms(x) + 74, "fundingRate": repr(v)} for x, v in t["fh"].items()
                        if start <= tms(x) + 74 <= end]
            return [{"t": tms(x), **{k: repr(float(t["hl"].loc[x, k])) for k in "ohlc"}}
                    for x in t["hl"].index if start <= tms(x) <= end]

        def fake_archive(path, name, manifest):
            sym = "BTCUSDT" if "BTCUSDT" in name else "ETHUSDT"
            coin = "BTC" if sym == "BTCUSDT" else "ETH"
            t = truth[coin]
            if "fundingRate" in path:
                m = name[-7:]
                if m == "2027-04":
                    return None                                     # mensual aún no publicado
                fb = t["fb"][t["fb"].index.strftime("%Y-%m") == m]
                return pd.DataFrame({"calc_time": [tms(x) + 2 for x in fb.index],
                                     "funding_interval_hours": 8, "last_funding_rate": fb.to_numpy()})
            key = name.split("-1h-")[1]
            if "monthly" in path and key == "2027-04":
                return None
            sel = t["bn"][t["bn"].index.strftime("%Y-%m-%d" if "daily" in path else "%Y-%m") == key]
            return pd.DataFrame([[tms(x), r.o, r.h, r.l, r.c, 1, tms(x) + 3599999, 0, 0, 0, 0, 0]
                                 for x, r in sel.iterrows()])

        def fake_effr(a, b, manifest):
            d = pd.date_range(a.normalize(), b.normalize(), freq="B")
            return pd.DataFrame({"date": d.strftime("%Y-%m-%d"), "rate": 0.036})

        orig = (S.hl_paged, S.archive_csv, S.effr_download)
        S.hl_paged, S.archive_csv, S.effr_download = fake_hl_paged, fake_archive, fake_effr
        try:
            res = S.forward(Path(td) / "collector", Path(td) / "out", Path(td) / "rep",
                            now=S.T1 + pd.Timedelta(days=2))
        finally:
            S.hl_paged, S.archive_csv, S.effr_download = orig
        effr = S.load_effr(Path(td) / "out" / "effr.csv")
        ok = True
        detail = []
        for coin in S.COINS:
            t = truth[coin]
            g, gq = S.build_grid(S.T0, S.T1, t["bn"], t["hl"])
            fh, fb = t["fh"], t["fb"]
            q = S.quality_verdict(gq, S.funding_quality(fh, fb, S.T0, S.T1))
            ref = S.run_window(coin, g, fh, fb, effr, S.T0, S.T1, 0.0, q)
            got = res["results"][coin]
            same = (abs(got["base"]["excess_ann"] - ref["base"]["excess_ann"]) < 1e-12
                    and abs(got["base"]["max_dd"] - ref["base"]["max_dd"]) < 1e-12
                    and got["quality"]["valid"] and got["checks"] == ref["checks"])
            notes = res["data_notes"][coin]
            ok &= same and notes["hl_funding_mismatch"] == 1 and notes["hl_candle_mismatch"] == 0 \
                and notes["hl_funding_only_in_collector"] == 0 \
                and notes["bn_funding_from_rest"] > 0 and notes["bn_klines_archive_vs_rest_maxreldiff"] < 1e-12
            detail.append(f"{coin}: same={same} notes={notes}")
        check("T forward() de punta a punta = verdad sintética (REST de abril, funding alterado detectado)",
              ok, " | ".join(detail))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # consola cp1252
    for fn in (case_closed_form, case_delta_neutral, case_price_gap, case_rebalance, case_liquidations,
               case_newey_west, case_evaluate, case_quality, case_parsing, case_guard,
               case_end_to_end, case_collector_store, case_forward_plumbing):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            check(f"{fn.__name__} EXCEPCIÓN", False, repr(e))
    bad = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f"  [{detail}]" if (detail and not ok) else ""))
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} casos OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
