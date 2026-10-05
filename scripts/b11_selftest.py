"""B11 — verificación con datos SINTÉTICOS de scripts/b11_positioning_study.py (antes de
bajar datos reales). Sin red. Uso: python scripts/b11_selftest.py  (salida != 0 si falla)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import b11_positioning_study as P  # noqa: E402

DAY = pd.Timedelta(days=1)
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))


def five_min(start: str, days: int, values, drop_day: int | None = None, drop_n: int = 0) -> pd.DataFrame:
    ts = pd.date_range(pd.Timestamp(start, tz="UTC") + pd.Timedelta(minutes=5), periods=days * 288,
                       freq="5min", unit="ns")
    v = np.asarray(values(np.arange(len(ts))), dtype=float)
    df = pd.DataFrame({"ts_ms": ts.as_unit("ms").asi8, "oi": v, "tt": v})
    if drop_day is not None:
        lo = drop_day * 288
        df = df.drop(df.index[lo:lo + drop_n])
    return df


def case_daily_stock() -> None:
    m = five_min("2022-01-01", 3, lambda i: i, drop_day=1, drop_n=200)
    v, cnt = P.daily_stock(m, "oi")
    d0 = pd.Timestamp("2022-01-01", tz="UTC")
    check("1 valor diario = registro de las 00:00 del día siguiente (cierra el día)",
          v.loc[d0] == 287.0, str(v.head(3).to_dict()))
    check("1 día con < 144 registros -> NaN", np.isnan(v.loc[d0 + DAY]) and cnt.loc[d0 + DAY] == 88)
    mz = five_min("2022-01-01", 2, lambda i: i + 1.0)
    mz.loc[mz.index[287], "oi"] = 0.0             # cierre del día 0 en 0 (imposible)
    vz, cz = P.daily_stock(mz, "oi")
    check("1 adenda 1b: OI <= 0 = faltante; el día cierra con el último registro válido",
          vz.loc[d0] == 287.0 and cz.loc[d0] == 287)


def case_tt1b_window() -> None:
    orig = P.W0
    try:
        P.W0 = P.TT1B_W0
        b = synthetic_books(True, 9)
        r = P.run_hypothesis("H-TT1", b)
        trs = P.trades_for(b["BTCUSDT"]["sig"]["H-TT1"]["side"], b["BTCUSDT"]["close"])
        ok = (P.W0 == pd.Timestamp("2022-12-15", tz="UTC") and min(t["entry"] for t in trs) >= P.TT1B_W0
              and r["days"] == (P.W1 - P.TT1B_W0).days)
    finally:
        P.W0 = orig
    check("12 adenda 1c: H-TT1b opera solo en 2022-12-15 -> 2024-10-01", ok)


def case_zscore_no_lookahead() -> None:
    idx = pd.date_range("2022-01-01", periods=200, freq="D", tz="UTC", unit="ns")
    rng = np.random.default_rng(1)
    v = pd.Series(rng.normal(size=200), index=idx)
    z1 = P.zscore(v)
    v2 = v.copy()
    v2.iloc[150:] += 100.0                     # cambiar el futuro
    z2 = P.zscore(v2)
    check("2 z-score sin mirar el futuro (z_t solo usa días < t)",
          np.allclose(z1.iloc[:150].fillna(0), z2.iloc[:150].fillna(0)))
    prev = v.iloc[60:150]
    exp = (v.iloc[150] - prev.mean()) / prev.std()
    check("2 z_t = (v_t − media 90 previos)/desvío 90 previos", abs(z1.iloc[150] - exp) < 1e-12)
    check("2 menos de 60 válidos -> NaN", z1.iloc[:60].isna().all() and not np.isnan(z1.iloc[60]))


def mk_close(days: pd.DatetimeIndex, rets: np.ndarray) -> pd.Series:
    return pd.Series(100 * np.cumprod(1 + rets), index=days)


def case_trades_and_book() -> None:
    days = pd.date_range(P.W0 - 10 * DAY, P.W1, freq="D", unit="ns")
    rets = np.full(len(days), 0.01)
    close = mk_close(days, rets)
    side = pd.Series(0.0, index=days)
    d_sig = P.W0 + 5 * DAY
    side.loc[d_sig] = 1.0
    side.loc[d_sig + DAY] = -1.0               # solapa: se ignora
    side.loc[d_sig + 3 * DAY] = -1.0           # libre de nuevo: entra
    side.loc[P.W0 - 2 * DAY] = 1.0             # entraría antes de W0: se ignora
    side.loc[P.W1 - 3 * DAY] = 1.0             # saldría después de W1: se ignora
    trs = P.trades_for(side, close)
    check("3 trades: sin solapamiento, dentro de [W0, W1], entrada al cierre del día",
          len(trs) == 2 and trs[0]["entry"] == d_sig + DAY and trs[0]["exit"] == d_sig + 4 * DAY
          and trs[1]["entry"] == d_sig + 4 * DAY, str([(t["entry"], t["exit"]) for t in trs]))
    empty_f = pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC").as_unit("ns"))
    rf0 = pd.Series(0.0, index=pd.date_range(P.W0, P.W1 - DAY, freq="D", unit="ns"))
    ex = P.book_daily(trs[:1], close, empty_f, rf0, 1.0)
    c = P.FEE + P.SLIP
    t0 = trs[0]["entry"]
    got = [ex.loc[t0], ex.loc[t0 + DAY], ex.loc[t0 + 2 * DAY]]
    exp = [0.01 - c, 0.01, 0.01 - c]
    check("4 libro diario long: +1 %/día, costo el día de entrada y el de salida",
          np.allclose(got, exp, atol=1e-12) and (ex.drop([t0, t0 + DAY, t0 + 2 * DAY]) == 0).all(), str(got))
    ex_s = P.book_daily(trs[1:], close, empty_f, rf0, 1.0)
    check("4 libro diario short: −1 %/día", abs(ex_s.loc[trs[1]["entry"] + DAY] + 0.01) < 1e-12)
    fund = pd.Series([0.001], index=pd.DatetimeIndex([t0 + pd.Timedelta(hours=8)]).as_unit("ns"))
    ex_f = P.book_daily(trs[:1], close, fund, rf0, 1.0)
    check("5 funding: el long paga la liquidación positiva en su día",
          abs(ex_f.loc[t0] - (0.01 - c - 0.001)) < 1e-12)
    rf = rf0 + 0.0001
    pt = P.trade_stats(trs[:1], fund, rf)
    exp_pt = (close.loc[t0 + 2 * DAY] / close.loc[t0 - DAY] - 1) - 0.001 - 2 * c - ((1.0001) ** 3 - 1)
    check("6 retorno por trade = fórmula de H-POS1 (precio, funding, costos, tasa libre)",
          abs(pt[0] - exp_pt) < 1e-12, f"{pt[0]} vs {exp_pt}")
    ex2 = P.book_daily(trs[:1], close, empty_f, rf0, 2.0)
    check("6 costos x2", abs(ex2.loc[t0] - (0.01 - 2 * c)) < 1e-12)


def case_signal_directions() -> None:
    days = pd.date_range("2021-01-01", periods=400, freq="D", tz="UTC", unit="ns")
    rng = np.random.default_rng(2)
    base = rng.normal(0, 0.01, len(days))
    k = 300
    rets = base.copy()
    rets[k] = 0.05                                 # día k sube fuerte
    close = 100 * np.cumprod(1 + rets)
    oi_d = 1000 * np.cumprod(1 + rng.normal(0, 0.002, len(days)))
    oi_d[k:] *= 1.2                                # salto de OI el día k
    tt_d = 1 + rng.normal(0, 0.01, len(days))
    tt_d[k] = 2.0                                  # top traders muy long
    vol = np.full(len(days), 1000.0)
    tb = 500 + rng.normal(0, 5, len(days))
    tb[k] = 800                                    # compra agresiva extrema
    # métricas 5 min: valor del día = registro de las 00:00 siguientes
    rows = []
    for i, d in enumerate(days):
        rows.append({"ts_ms": int((d + DAY).timestamp() * 1000), "oi": oi_d[i], "tt": tt_d[i]})
        for j in range(1, 150):
            rows.append({"ts_ms": int((d + pd.Timedelta(minutes=5 * j)).timestamp() * 1000), "oi": oi_d[i], "tt": tt_d[i]})
    m = pd.DataFrame(rows).drop_duplicates("ts_ms", keep="first").sort_values("ts_ms")
    kl = pd.DataFrame({"open_time_ms": days.as_unit("ms").asi8, "close": close, "volume": vol,
                       "taker_buy_volume": tb})
    sig = P.signals(m, kl, days)
    d = days[k]
    check("7 H-OI1: OI extremo con día alcista -> SHORT (contraria al día)", sig["H-OI1"]["side"].loc[d] == -1.0,
          str(sig["H-OI1"]["z"].loc[d]))
    check("7 H-TT1: top traders muy long -> LONG (seguir)", sig["H-TT1"]["side"].loc[d] == 1.0)
    check("7 H-TK1: compra taker extrema -> SHORT (contraria)", sig["H-TK1"]["side"].loc[d] == -1.0)


def synthetic_books(planted: bool, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    days = pd.date_range(pd.Timestamp(f"{P.KLINES_FROM}-01", tz="UTC"), P.W1, freq="D", unit="ns")
    rf_d = pd.Series(0.03 / 360, index=pd.date_range(P.W0, P.W1 - DAY, freq="D", unit="ns"))
    books = {}
    for sym in P.SYMBOLS:
        tt = rng.normal(0, 1, len(days))
        rets = rng.normal(0, 0.02, len(days))
        if planted:                                 # tras z alto, 3 días de +1.5 %/día
            fire = np.where(np.abs(tt) > 2.0)[0]
            for i in fire:
                rets[i + 1:i + 4] = 0.015 * np.sign(tt[i])
        close = pd.Series(100 * np.cumprod(1 + rets), index=days)
        v = pd.Series(tt, index=days)
        z = P.zscore(v)
        side = np.sign(z).where(z.abs() > P.Z, 0.0).fillna(0.0)
        sig = {h: {"v": v, "z": z, "side": side} for h in P.HYPS}
        fund = pd.Series(0.0001, index=pd.date_range(days[0], P.W1, freq="8h", unit="ns"))
        books[sym] = {"sig": sig, "close": close, "fund": fund, "rf_d": rf_d, "start": days[0]}
    return books


def case_end_to_end() -> None:
    good = P.run_hypothesis("H-TT1", synthetic_books(True, 5))
    bad = P.run_hypothesis("H-TT1", synthetic_books(False, 6))
    check("8 señal sembrada fuerte -> PASA", good["pasa"], str({k: good[k] for k in ("excess_ann", "t_nw", "n_trades")}))
    check("8 ruido puro -> NO PASA", not bad["pasa"], str({k: bad[k] for k in ("excess_ann", "t_nw", "n_trades")}))
    b = synthetic_books(True, 5)
    v = b["ETHUSDT"]["sig"]["H-TT1"]["v"].copy()
    gaps = v[(v.index >= P.W0)].sample(frac=0.15, random_state=1).index
    v.loc[gaps] = np.nan
    b["ETHUSDT"]["sig"] = {h: dict(b["ETHUSDT"]["sig"][h], v=v) for h in P.HYPS}
    r = P.run_hypothesis("H-TT1", b)
    check("9 cobertura < 90 % -> el símbolo queda fuera", r["symbols"] == ["BTCUSDT"] and r["coverage"]["ETHUSDT"] < 0.9)
    for s in P.SYMBOLS:
        b[s]["sig"] = {h: dict(b[s]["sig"][h], v=v) for h in P.HYPS}
    r2 = P.run_hypothesis("H-TT1", b)
    check("9 ambos símbolos inválidos -> hipótesis INVÁLIDA (no puede pasar)",
          not r2["pasa"] and not r2["checks"]["6_datos_validos"])


def case_parsing() -> None:
    raw = pd.DataFrame({"create_time": ["2022-01-01 00:05:00", "2022-01-01 00:10:00"], "symbol": "BTCUSDT",
                        "sum_open_interest": ["10", "11"], "sum_open_interest_value": [1, 1],
                        "count_toptrader_long_short_ratio": [1, 1], "sum_toptrader_long_short_ratio": [1.5, 1.6],
                        "count_long_short_ratio": [1, 1], "sum_taker_long_short_vol_ratio": [1, 1]})
    a = P.norm_metrics(raw)
    ms0 = int(pd.Timestamp("2022-01-01 00:05", tz="UTC").timestamp() * 1000)
    check("10 metrics: create_time texto -> ms UTC; columnas por nombre",
          a["ts_ms"].iloc[0] == ms0 and a["oi"].tolist() == [10.0, 11.0] and a["tt"].tolist() == [1.5, 1.6])
    b = P.norm_metrics(raw.drop(columns=["sum_toptrader_long_short_ratio"]).assign(create_time=[ms0, ms0 + 300000]))
    check("10 metrics: create_time en ms y columna faltante -> NaN", b["ts_ms"].iloc[0] == ms0 and b["tt"].isna().all())
    row = [1640995200000, "1", "2", "0.5", "1.5", "100", 1641081599999, "150", 10, "60", "90", "0"]
    k1 = P.norm_klines_1d(pd.DataFrame([row]))
    k2 = P.norm_klines_1d(pd.DataFrame([[row[0] * 1000] + row[1:]]))
    check("11 klines 1d: close, volumen y taker por posición; µs -> ms",
          k1.equals(k2) and k1.iloc[0].tolist() == [1640995200000, 1.5, 100.0, 60.0])


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for fn in (case_daily_stock, case_zscore_no_lookahead, case_trades_and_book, case_signal_directions,
               case_end_to_end, case_parsing, case_tt1b_window):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            import traceback
            check(f"{fn.__name__} EXCEPCIÓN", False, repr(e) + traceback.format_exc()[-600:])
    bad = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        print(f"{'OK  ' if ok else 'FAIL'} {name}" + (f"  [{detail}]" if (detail and not ok) else ""))
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} casos OK")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
