"""B13 — verificación con datos SINTÉTICOS de scripts/b13_cross_factors.py (antes de bajar
datos reales). Sin red. Uso: python scripts/b13_selftest.py  (salida != 0 si falla)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import b13_cross_factors as X  # noqa: E402

STEP = X.STEP
C = X.FEE + X.SLIP
RESULTS: list[tuple[str, bool, str]] = []
EFFR = pd.Series(0.02, index=pd.date_range("2019-10-01", "2024-10-01", freq="D", tz="UTC", unit="ns"))


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))


def grid(start="2019-11-01", end="2024-10-01") -> pd.DatetimeIndex:
    return pd.date_range(pd.Timestamp(start, tz="UTC") + STEP, pd.Timestamp(end, tz="UTC"), freq="8h", unit="ns")


def make_w(n: int, prices: np.ndarray | None = None, vol: float = 6e7, g=None) -> dict:
    g = grid() if g is None else g
    syms = [f"S{i:02d}USDT" for i in range(n)]
    p = np.full((len(g), n), 100.0) if prices is None else prices
    return {"perp": pd.DataFrame(p, index=g, columns=syms),
            "perp_qv": pd.DataFrame(vol / 3, index=g, columns=syms),
            "funding": pd.DataFrame(0.0, index=g, columns=syms)}


def case_closed_form() -> None:
    w = make_w(12)
    r = X.run("H-REV1", w)
    got = float(r["curve"].iloc[-1])
    check("1 precios fijos: entra una vez, nunca rota (empates estables), sale al final -> 1 − 2c",
          abs(got - (1 - 2 * C)) < 1e-12 and r["weeks_invested"] == 247, f"{got} vs {1 - 2 * C}")
    w["funding"].loc[:, :] = 0.0003
    r2 = X.run("H-REV1", w)
    check("2 funding igual para todos: long paga y short cobra lo mismo -> neto 0",
          abs(float(r2["curve"].iloc[-1]) - (1 - 2 * C)) < 1e-12)
    w3 = make_w(12)
    w3["funding"].loc[:, ["S10USDT", "S11USDT"]] = 0.0001       # solo en los shorts (últimos en orden)
    r3 = X.run("H-REV1", w3)
    wk1 = float(r3["curve"].loc[X.START + pd.Timedelta(days=7)])
    exp = (1 - C) + 21 * 0.5 * 0.0001                          # nocional del short = 0.5·eq(1.0)
    check("2 el short cobra el funding de sus nombres (1ª semana exacta)",
          abs(wk1 - exp) < 1e-12, f"{wk1} vs {exp}")


def case_ranking() -> None:
    w = make_w(12)
    T = X.START
    i = w["perp"].index.get_loc(T)
    # último retorno semanal distinto por símbolo: S00 el peor ... S11 el mejor
    for j, s in enumerate(w["perp"].columns):
        w["perp"].loc[w["perp"].index[i - X.LB + 1]:, s] = 100.0 * (1 + 0.01 * j)
    sig = X.signal_at("H-REV1", w, i, list(w["perp"].columns))
    order = list(sig.sort_values(kind="mergesort").index)
    check("3 H-REV1: señal = retorno T−7d -> T; perdedores primero (long)",
          order[:2] == ["S00USDT", "S01USDT"] and order[-2:] == ["S10USDT", "S11USDT"])
    f = make_w(12)
    fi = f["perp"].index
    f["funding"].loc[fi[i - X.LB], "S05USDT"] = 1.0       # liquidado en T − 7 d: NO entra
    f["funding"].loc[fi[i], "S06USDT"] = 1.0              # liquidado en T: SÍ entra
    s2 = X.signal_at("H-FND1", f, i, list(f["perp"].columns))
    check("4 H-FND1: suma del funding en (T − 7 d, T]", s2["S05USDT"] == 0 and s2["S06USDT"] == 1.0)


def case_q_and_liquidity() -> None:
    r = X.run("H-REV1", make_w(9))
    check("5 menos de 10 elegibles (q < 2) -> efectivo todas las semanas",
          r["weeks_invested"] == 0 and abs(float(r["curve"].iloc[-1]) - 1.0) < 1e-15)
    w = make_w(10)                                         # con S03 serían 10 (q=2); sin S03, 9 (q=1)
    w["perp_qv"].loc[:, "S03USDT"] = 1e6 / 3
    day_T = w["perp_qv"].index[(w["perp_qv"].index > X.START) & (w["perp_qv"].index <= X.START + pd.Timedelta(days=1))]
    w["perp_qv"].loc[day_T, "S03USDT"] = 1e12              # pico el mismo día: no debe contar
    r2 = X.run("H-REV1", w)
    check("6 filtro de liquidez solo con días previos (pico del día no habilita)",
          r2["n_side"][0] == 1 and r2["weeks_invested"] == 0, str(r2["n_side"][:3]))


def case_delisting() -> None:
    w = make_w(12)
    cut = pd.Timestamp("2022-06-01 08:00", tz="UTC")
    w["perp"].loc[w["perp"].index > cut, "S00USDT"] = np.nan   # S00 (long) deja de existir
    r = X.run("H-REV1", w)
    cv = r["curve"]
    after = cv[cv.index > cut].iloc[0]
    before = cv[cv.index <= cut].iloc[-1]
    drop = before - after                                        # nocional de S00 = 0.5·eq/2 ≈ 0.25
    check("7 deslistado: sale al último precio con 2 % + costo sobre su nocional",
          r["delistings"] == 1 and abs(drop - (X.DELIST_PENALTY + C) * 0.25) < 1e-4, f"drop {drop}")


def planted(hyp: str, strength: float, seed: int) -> dict:
    rng = np.random.default_rng(seed)
    g = grid()
    n = 25
    ret = rng.normal(0, 0.006, (len(g), n))
    fund = rng.normal(0.0001, 0.0001, (len(g) // 21 + 2, n))     # funding constante por semana
    fmat = np.repeat(fund, 21, axis=0)[:len(g)]
    if strength:
        mondays = [k for k, t in enumerate(g) if t.weekday() == 0 and t.hour == 0]
        p = 100 * np.cumprod(1 + ret, axis=0)
        for k in mondays:
            if k < 21 or k + 21 > len(g):
                continue
            if hyp == "H-REV1":
                p = 100 * np.cumprod(1 + ret, axis=0)
                key = p[k] / p[k - 21] - 1
            else:
                key = fmat[k - 20:k + 1].sum(axis=0)
            order = np.argsort(key, kind="mergesort")
            lo, hi = order[:5], order[-5:]
            ret[k + 1:k + 22, lo] += strength / 21
            ret[k + 1:k + 22, hi] -= strength / 21
    w = make_w(n, prices=100 * np.cumprod(1 + ret, axis=0), g=g)
    w["funding"] = pd.DataFrame(fmat, index=g, columns=w["perp"].columns)
    return w


def case_end_to_end() -> None:
    for hyp in X.HYPS:
        good = X.evaluate_hyp(hyp, planted(hyp, 0.03, 1), EFFR)
        bad = X.evaluate_hyp(hyp, planted(hyp, 0.0, 2), EFFR)
        check(f"8 {hyp}: efecto sembrado (+3 %/semana entre quintiles) -> PASA", good["pasa"],
              str({k: good[k] for k in ("excess_ann", "t_nw", "max_dd")}))
        check(f"8 {hyp}: ruido puro -> NO PASA", not bad["pasa"],
              str({k: bad[k] for k in ("excess_ann", "t_nw")}))


def case_parsing_and_window() -> None:
    row = [1577836800000, "1", "2", "0.5", "1.5", "10", 1577865599999, "15", 3, "5", "7", "0"]
    a = X.norm_klines_8h(pd.DataFrame([row]))
    b = X.norm_klines_8h(pd.DataFrame([[row[0] * 1000] + row[1:]],
                                      columns=["open_time", "o", "h", "l", "c", "v", "ct", "qv", "n", "tb", "tq", "ig"]))
    check("9 klines 8h: close y volumen en USDT por posición; µs -> ms", a.equals(b) and a.iloc[0].tolist() == [1577836800000, 1.5, 15.0])
    ev = X.B.evaluate(pd.Series(1.0, index=pd.date_range(X.START, X.END, freq="8h", unit="ns")), EFFR, X.START, X.END)
    check("10 ventana: 247 semanas lunes -> lunes (2020-01-06 -> 2024-09-30)", ev["weeks"] == 247)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for fn in (case_closed_form, case_ranking, case_q_and_liquidity, case_delisting, case_end_to_end,
               case_parsing_and_window):
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
