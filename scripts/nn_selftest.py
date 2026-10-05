"""H-NN1 — verificación con datos SINTÉTICOS de scripts/nn_microstructure_experiment.py
(antes de bajar datos reales). Sin red. Uso: python scripts/nn_selftest.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nn_microstructure_experiment as N  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))


def synth_df(days: int, start: int, seed: int, planted: bool) -> pd.DataFrame:
    """Segundos con libro L1. Si planted: el retorno de t+1 depende del OBI de t-10."""
    rng = np.random.default_rng(seed)
    n = days * 86_400
    obi = rng.uniform(-1, 1, n)
    noise = rng.normal(0, 0.6, n)
    drift = np.zeros(n)
    if planted:
        drift[11:] = 0.6 * obi[:-11]                 # r_{t+1} usa obi_{t-10}
    logmid = np.log(30_000.0) + np.cumsum((drift + noise) / 1e4)
    mid = np.exp(logmid)
    half = mid * 0.05 / 1e4
    return pd.DataFrame({
        "bid": mid - half, "ask": mid + half,
        "bq": 5 * (1 + obi), "aq": 5 * (1 - obi),
        "ofi": rng.normal(0, 1, n), "n_upd": 10,
        "buy_vol": rng.exponential(1, n), "sell_vol": rng.exponential(1, n),
        "n_tr": rng.poisson(5, n),
    }, index=pd.RangeIndex(start, start + n, name="sec"))


def case_seq_alignment() -> None:
    n = 200
    X = np.arange(n * 23, dtype=np.float32).reshape(n, 23)
    Xs = X[:, N.seq_index()]
    rows = np.array([10, 40, 199])
    M, ok = N.seq_matrix(X, Xs, rows)
    lag3 = M[1, 23 + 2 * 5: 23 + 3 * 5]               # lag 3 de la fila 40
    check("1 secuencia: 23 features en t + lag k = fila t-k (solo pasado)",
          M.shape == (3, 173) and np.array_equal(M[1, :23], X[40]) and np.array_equal(lag3, Xs[37])
          and list(ok) == [False, True, True])
    Xs2 = Xs.copy()
    Xs2[50, 0] = np.nan
    ok2 = N.seq_ok_mask(X, Xs2, np.array([50, 51, 80, 81]))
    check("1 NaN en la historia invalida las 30 filas siguientes", list(ok2) == [True, False, False, True],
          str(ok2))


def case_checksum_and_metrics() -> None:
    sha = "a" * 64
    check("2 checksum oficial: '<sha>  archivo.zip' -> sha; vacío/raro -> None",
          N.parse_checksum(f"{sha}  BTCUSDT-bookTicker-2023-05-17.zip\n") == sha
          and N.parse_checksum("") is None and N.parse_checksum("404 Not Found") is None)
    rng = np.random.default_rng(1)
    sec = np.repeat(np.arange(3) * 86_400, 500) + np.tile(np.arange(500), 3)
    y = rng.choice([-1, 0, 1], len(sec))
    s1, s2 = rng.normal(size=len(sec)), rng.normal(size=len(sec))
    a1, a2 = N.daily_auc(sec, y, s1, 0), N.daily_auc(sec, y, s2, 0)
    m = (sec < 86_400) & (y != 0)
    pd_ = N.paired_days(a1, a2)
    d = np.array([a1[k] - a2[k] for k in range(3)])
    check("3 AUC diaria y t pareado por días = cálculo directo",
          abs(a1[0] - roc_auc_score(y[m] == 1, s1[m])) < 1e-12
          and abs(pd_["t"] - d.mean() / (d.std(ddof=1) / np.sqrt(3))) < 1e-9)


def windows(planted: bool, seed: int):
    t0 = 1_700_000_000 - (1_700_000_000 % 86_400)
    tr = synth_df(4, t0, seed, planted)
    te = synth_df(3, t0 + 10 * 86_400, seed + 1, planted)
    W_tr = N.window_from_df("train", tr, [], 4)
    W_te = N.window_from_df("test", te, [], 3)
    return W_tr, W_te, t0 + 3 * 86_400


def case_planted_sequence_wins() -> None:
    W_tr, W_te, split = windows(True, 10)
    check("4 ventanas cargadas por separado: el arranque de la prueba no ve la ventana anterior",
          not W_te.feat_ok[:299].any())
    r = N.run_horizon(30, 4.0, W_tr, split, W_te, None, models=("hgb", "mlpseq"))
    a_h, a_s = r["models"]["hgb"]["auc_test"], r["models"]["mlpseq"]["auc_test"]
    v = r["models"]["mlpseq"]["vs_hgb_daily"]
    check("5 info en la secuencia: MLP-SEQ le gana al HGB (la red ve el OBI pasado)",
          a_s > a_h + 0.05 and v["mean_delta"] > N.MIN_DAUC, f"hgb {a_h:.3f} seq {a_s:.3f} {v}")
    e = r["models"]["mlpseq"]["econ_test"]["lat0"]
    check("5 economía calculada en los 4 escenarios y 2 latencias",
          set(e) == set(N.MS.FEE_SCENARIOS) and "lat1" in r["models"]["mlpseq"]["econ_test"])


def case_noise_nobody_wins() -> None:
    W_tr, W_te, split = windows(False, 20)
    r = N.run_horizon(30, 4.0, W_tr, split, W_te, None, models=("hgb", "mlpseq"))
    a_h, a_s = r["models"]["hgb"]["auc_test"], r["models"]["mlpseq"]["auc_test"]
    v = r["models"]["mlpseq"]["vs_hgb_daily"]
    check("6 ruido puro: AUC ~0.5 y la red NO 'le gana' (Δ < 0.010)",
          abs(a_h - 0.5) < 0.02 and abs(a_s - 0.5) < 0.02 and v["mean_delta"] is not None
          and v["mean_delta"] < N.MIN_DAUC,
          f"hgb {a_h:.3f} seq {a_s:.3f} {v}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for fn in (case_seq_alignment, case_checksum_and_metrics, case_planted_sequence_wins,
               case_noise_nobody_wins):
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
