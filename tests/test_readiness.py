"""v3.3.0 — tests del comando /readiness (read-only, evalua gates para dinero real).

NO habilita nada: real-money sigue bloqueado. Verifica el dispatch, el veredicto honesto
(NO LISTO), y que los gates de edge/data reflejen la data del repo.
"""

from __future__ import annotations

from dataclasses import replace

from app.assistant.command_handler import BasicTelegramAssistant
from tests.test_score import _settings


def _strat(name, cat, trades, avg_r):
    return {"strategy_name": name, "category": cat, "trades": trades, "avg_r": avg_r}


class _FakeRepo:
    def __init__(self, strat_rows=None, n_feat=68, trades=None, executed=None, balance="88000"):
        self._strat = strat_rows or []
        self._n_feat = n_feat
        self._trades = trades or []
        self._executed = set(executed or [])
        self._balance = balance

    def fetch_strategy_performance(self, limit=50):
        return list(self._strat)

    def count_closed_trades_with_features(self):
        return self._n_feat

    def fetch_closed_trades_since(self, since):
        return [t for t in self._trades if str(t.get("closed_at") or "") >= since]

    def fetch_closed_paper_trades(self, limit=5000):
        return list(self._trades)

    def fetch_executed_paper_trade_ids(self):
        return set(self._executed)

    def get_state(self, key, default=None):
        return self._balance if key == "account_balance" else default


def _bot(repo, **over):
    return BasicTelegramAssistant(
        replace(_settings(), performance_baseline_date="2026-06-03", **over), repo
    )


def test_readiness_dispatch_and_honest_verdict():
    bot = _bot(_FakeRepo())
    msg = bot.handle("/readiness")
    assert "Readiness para dinero real" in msg
    assert "NO LISTO" in msg
    assert "bloqueado" in msg  # deja claro que no habilita nada
    # aliases
    assert "Readiness para dinero real" in bot.handle("/listo")
    assert "Readiness para dinero real" in bot.handle("real money")


def test_readiness_edge_gate_no_candidate():
    bot = _bot(_FakeRepo(strat_rows=[_strat("momentum", "forex", 26, -0.45)]))  # n>=30? no, y -R
    msg = bot.handle("/readiness")
    assert "[X] Edge" in msg


def test_readiness_edge_gate_with_candidate_is_unconfirmed():
    # estrategia +R con muestra -> candidato, pero marcado [!] (sin confirmar fuera de regimen)
    bot = _bot(_FakeRepo(strat_rows=[_strat("forex_session_breakout", "forex", 86, 0.378)]))
    msg = bot.handle("/readiness")
    assert "[!] Edge: candidato forex_session_breakout/forex" in msg
    assert "Sin confirmar" in msg


def test_readiness_data_gate_shows_progress():
    bot = _bot(_FakeRepo(n_feat=68))
    msg = bot.handle("/readiness")
    assert "[X] Data con features: 68/400" in msg


def test_readiness_lists_all_five_gates_and_disclaimer():
    msg = _bot(_FakeRepo()).handle("/readiness")
    assert "Edge:" in msg
    assert "Data con features:" in msg
    assert "Performance limpia" in msg
    assert "Sizing para cuenta micro:" in msg
    assert "Ejecucion real:" in msg
    assert "No es recomendacion financiera" in msg  # disclaimer
