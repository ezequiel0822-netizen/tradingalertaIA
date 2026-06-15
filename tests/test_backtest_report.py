"""Tests del report del backtest harness (v3.6.0, ESPEC §11 / §12 / §14).

Slices con n<30 sin [OK]; veredicto criterio por criterio; stress ×1.5 presente.
Se siembran run + trades directo en las tablas backtest_* y se genera el reporte.
"""

import json
from pathlib import Path
from uuid import uuid4

from app.backtest.report import evaluate_verdict, generate_report
from app.database.db import init_db
from app.database.repository import Repository
from tests.test_score import _settings

_DAY = 86_400


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"btreport_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _trade(i: int, direction: str, r_net: float, year: int) -> dict:
    return {
        "config_id": 0, "strategy": "breakout", "symbol": "EURUSD",
        "category": "forex", "direction": direction,
        "signal_bar_utc": i * _DAY, "entry_utc": i * _DAY,
        "entry_price": 100.0, "sl_initial": 98.0, "tp_initial": 104.0,
        "exit_utc": (i + 1) * _DAY, "exit_price": 100.0 + r_net,
        "exit_reason": "time", "bars_held": 1,
        "r_gross": r_net + 0.0125, "cost_r": 0.0125, "r_net": r_net,
        "mfe_r": 0.5, "mae_r": 0.5, "session": "Asia",
        "regime_trend": "up", "regime_vol": "mid", "year": year,
    }


def _seed_run(repo: Repository) -> int:
    run_id = repo.insert_backtest_run({
        "mode": "A", "timeframe": "D1", "symbols": "EURUSD",
        "strategies": "breakout", "cost_multiplier": 1.25, "n_configs_tested": 1,
        "data_ranges_json": json.dumps({"EURUSD": {"bars": 8000}}),
        "config_json": "{}", "notes": "test",
    })
    trades = []
    for i in range(35):  # 35 longs -> slice con [OK]
        trades.append(_trade(i, "long", 0.05, 2019 + (i % 5)))
    for i in range(5):   # 5 shorts -> slice SIN [OK]
        trades.append(_trade(100 + i, "short", -0.10, 2020 + i))
    repo.insert_backtest_trades(run_id, trades)
    return run_id


def test_report_files_generated(tmp_path) -> None:
    repo = _repo()
    run_id = _seed_run(repo)
    paths = generate_report(repo, run_id, _settings(), out_base=str(tmp_path))
    assert Path(paths["report_md"]).exists()
    assert Path(paths["trades_csv"]).exists()
    assert Path(paths["equity_csv"]).exists()


def test_slice_ok_only_when_n_at_least_30(tmp_path) -> None:
    repo = _repo()
    run_id = _seed_run(repo)
    paths = generate_report(repo, run_id, _settings(), out_base=str(tmp_path))
    md = Path(paths["report_md"]).read_text(encoding="utf-8")
    long_line = next(ln for ln in md.splitlines() if ln.startswith("| long |"))
    short_line = next(ln for ln in md.splitlines() if ln.startswith("| short |"))
    assert "[OK]" in long_line       # n=35 >= 30
    assert "[OK]" not in short_line   # n=5 < 30


def test_report_has_verdict_and_stress(tmp_path) -> None:
    repo = _repo()
    run_id = _seed_run(repo)
    paths = generate_report(repo, run_id, _settings(), out_base=str(tmp_path))
    md = Path(paths["report_md"]).read_text(encoding="utf-8")
    assert "VEREDICTO por estrategia" in md
    assert "Muestra (n>=150)" in md
    assert "Stress de costos" in md
    assert "x1.5" in md              # el stress ×1.5 esta presente
    # n=40 < 150 -> NO PASA en muestra
    assert "NO PASA" in md


def test_verdict_criteria_cover_all_seven() -> None:
    repo = _repo()
    run_id = _seed_run(repo)
    trades = repo.fetch_backtest_trades(run_id)
    verdict = evaluate_verdict(trades, _settings())
    assert verdict["n"] == 40
    assert verdict["passes"] is False        # n<150
    assert len(verdict["criteria"]) == 7     # los 7 criterios del §11
    # la robustez de vecindad es N/A en Modo A (ok=None)
    assert any(ok is None for _, ok, _ in verdict["criteria"])


def test_top_trade_share_isolates_outlier() -> None:
    from app.backtest.report import _top_trade_share
    top1, top10 = _top_trade_share([100.0, 1.0, 1.0, -2.0])
    assert abs(top1 - 100.0 / 102.0) < 1e-9   # gananacia bruta = 102


def test_concentration_flags_single_trade_artifact(tmp_path) -> None:
    # 20 trades chicos + 1 monstruo (la situacion real de trend_following_d1 en
    # USDCHF sintetico): el reporte tiene que GRITAR que es un artefacto.
    repo = _repo()
    run_id = repo.insert_backtest_run({
        "mode": "A", "timeframe": "D1", "symbols": "USDCHF",
        "strategies": "trend_following_d1", "cost_multiplier": 1.25,
        "n_configs_tested": 1, "config_json": "{}", "notes": "test",
    })
    trades = [_trade(i, "long", 0.05, 2020) for i in range(20)]
    trades.append(_trade(999, "long", 500.0, 2020))  # un solo trade carga todo
    repo.insert_backtest_trades(run_id, trades)
    paths = generate_report(repo, run_id, _settings(), out_base=str(tmp_path))
    md = Path(paths["report_md"]).read_text(encoding="utf-8")
    assert "Concentracion" in md
    assert "ARTEFACTO" in md
