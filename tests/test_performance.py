"""v3.3.0 — tests de performance desde baseline limpio + comando /performance.

Verifica la funcion pura `performance_since` (filtro por baseline, solo ejecutados,
exclusion de artifacts, R neto de costos, win/loss, impacto USD en la cuenta) y el
dispatch del comando /performance. NO altera el balance real; es solo medicion.
"""

from __future__ import annotations

from dataclasses import replace

from app.assistant.command_handler import BasicTelegramAssistant
from app.portfolio.performance import performance_since
from tests.test_score import _settings


def _t(tid, *, entry, latest, ostop, closed_at, notional=10000.0, direction="long",
       category="forex", status="closed_by_time"):
    # unrealized_return_pct = retorno final almacenado (direction-aware simple)
    if direction == "short":
        final = (entry - latest) / entry * 100.0
    else:
        final = (latest - entry) / entry * 100.0
    return {
        "id": tid, "symbol": "EURUSD", "category": category, "direction": direction,
        "entry_price": entry, "latest_price": latest, "stop_loss": ostop,
        "original_stop_loss": ostop, "take_profit_1": entry * 1.02, "partial_closed": 0,
        "status": status, "closed_at": closed_at, "unrealized_return_pct": final,
        "size_notional": notional,
    }


def _win(tid, closed_at="2026-06-05T15:00:00+00:00", **o):
    return _t(tid, entry=100.0, latest=103.0, ostop=99.0, closed_at=closed_at, **o)  # r=+3


def _loss(tid, closed_at="2026-06-05T15:00:00+00:00", **o):
    return _t(tid, entry=100.0, latest=98.0, ostop=99.0, closed_at=closed_at, **o)  # r=-2


BASE = "2026-06-03"


# ----------------------------- funcion pura ------------------------------ #
def test_baseline_filters_pre_baseline_trades():
    pre = _win(1, closed_at="2026-05-22T10:00:00+00:00")   # periodo buggeado -> fuera
    post = _win(2, closed_at="2026-06-05T10:00:00+00:00")
    s = performance_since([pre, post], BASE, executed_ids={1, 2}, balance=100000.0)
    assert s.trades == 1 and s.wins == 1


def test_excludes_non_executed():
    # trade no ejecutado a MT5 (no esta en executed_ids) -> no toco el balance -> fuera.
    s = performance_since([_win(1)], BASE, executed_ids=set(), balance=100000.0)
    assert s.trades == 0


def test_excludes_artifacts():
    artifact = _t(1, entry=100.0, latest=100.0, ostop=99.0, closed_at="2026-06-05T10:00:00+00:00")
    s = performance_since([artifact], BASE, executed_ids={1}, balance=100000.0)
    assert s.trades == 0


def test_counts_wins_losses_net_r_and_win_rate():
    s = performance_since([_win(1), _loss(2)], BASE, executed_ids={1, 2}, balance=100000.0)
    assert s.trades == 2 and s.wins == 1 and s.losses == 1
    assert s.win_rate == 0.5
    assert s.net_r > 0  # +3 y -2 brutos -> +1 neto aprox


def test_near_zero_return_is_scratch():
    # Retorno minusculo (+0.01%) -> scratch, no win (misma scratch_eps que /expectancy).
    t = _t(1, entry=100.0, latest=100.01, ostop=99.0, closed_at="2026-06-05T10:00:00+00:00")
    s = performance_since([t], BASE, executed_ids={1}, balance=100000.0)
    assert s.trades == 1 and s.wins == 0 and s.losses == 0 and s.scratches == 1
    assert s.trades == s.wins + s.losses + s.scratches  # cuadra


def test_account_pct_from_usd_pnl():
    # win: notional 10k * +3% = +300 ; loss: 10k * -2% = -200 -> neto +100 / 100k = +0.1%
    s = performance_since([_win(1), _loss(2)], BASE, executed_ids={1, 2}, balance=100000.0)
    assert s.account_pct == 0.1


def test_empty_baseline_includes_all_executed():
    old = _win(1, closed_at="2026-05-10T10:00:00+00:00")
    s = performance_since([old], "", executed_ids={1}, balance=100000.0)
    assert s.trades == 1  # sin baseline -> cuenta todo lo ejecutado


def test_cost_model_reduces_net_r():
    trades = [_win(1)]
    gross = performance_since(trades, BASE, {1}, 100000.0, cost_pct_by_category=None)
    net = performance_since(trades, BASE, {1}, 100000.0, cost_pct_by_category={"forex": 0.5})
    assert net.net_r < gross.net_r  # el costo empeora el R


def test_balance_zero_safe():
    s = performance_since([_win(1)], BASE, {1}, balance=0.0)
    assert s.account_pct == 0.0  # no divide por cero


# ------------------------- comando /performance -------------------------- #
class _CmdRepo:
    def __init__(self, trades, executed, balance="100000"):
        self._trades = trades
        self._executed = set(executed)
        self._balance = balance

    def fetch_closed_trades_since(self, since):
        return [t for t in self._trades if str(t.get("closed_at") or "") >= since]

    def fetch_closed_paper_trades(self, limit=5000):
        return list(self._trades)

    def fetch_executed_paper_trade_ids(self):
        return set(self._executed)

    def get_state(self, key, default=None):
        return self._balance if key == "account_balance" else default


def test_performance_command_dispatch_and_format():
    repo = _CmdRepo([_win(1), _loss(2)], executed=[1, 2])
    bot = BasicTelegramAssistant(replace(_settings(), performance_baseline_date=BASE), repo)
    msg = bot.handle("/performance")
    assert f"Rendimiento desde {BASE}" in msg
    assert "Trades: 2 (1 ganados, 1 perdidos, 0 neutros)" in msg
    assert "Impacto en la cuenta" in msg
    assert "NO prueba edge" in msg  # disclaimer de honestidad presente
    # alias en espanol
    assert "Rendimiento desde" in bot.handle("/rendimiento")
