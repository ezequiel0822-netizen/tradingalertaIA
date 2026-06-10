"""v3.4.0 — tests del exit shadow (simulacion honesta de trailing sobre el camino de R)."""

from __future__ import annotations

from dataclasses import replace

from app.assistant.command_handler import BasicTelegramAssistant
from app.learning.exit_shadow import (
    analyze_closed_trades,
    compare_trailing,
    record_open_trade_samples,
    simulate_trailing_exit,
)
from tests.test_score import _settings


class _FakeRepo:
    def __init__(self, closed=None, paths=None):
        self.samples = []  # (tid, r, at)
        self._closed = closed or []
        self._paths = paths or {}

    def insert_r_sample(self, tid, r, at):
        self.samples.append((tid, r, at))

    def fetch_r_path(self, tid):
        return list(self._paths.get(tid, []))

    def fetch_closed_paper_trades(self, limit=5000):
        return list(self._closed)

    def fetch_closed_trades_since(self, since):
        return list(self._closed)


def _open(tid, entry, latest, stop, direction="long"):
    return {"id": tid, "entry_price": entry, "latest_price": latest,
            "original_stop_loss": stop, "stop_loss": stop, "direction": direction,
            "partial_closed": 0, "take_profit_1": (entry * 1.02 if entry else None)}


def _closed_forex(tid, latest):
    return {"id": tid, "category": "forex", "status": "closed_by_time",
            "closed_at": "2026-06-09T10:00:00+00:00", "entry_price": 100.0,
            "latest_price": latest, "original_stop_loss": 99.0, "stop_loss": 99.0,
            "direction": "long", "partial_closed": 0, "take_profit_1": 102.0}


def test_trailing_exits_on_first_giveback_not_global_peak():
    # sube a 2, cae a 0.5 (giveback 1.5 > 1) -> sale en 2-1=1, AUNQUE despues recupere a 1.5
    path = [0.0, 2.0, 0.5, 1.5, 0.0]
    assert simulate_trailing_exit(path, distance=1.0) == 1.0


def test_trailing_not_triggered_when_monotonic_up_returns_final():
    path = [0.0, 0.5, 1.0, 2.0, 3.0]  # nunca devuelve 1R
    assert simulate_trailing_exit(path, distance=1.0) == 3.0


def test_trailing_on_clean_loser_matches_final():
    # perdedor directo: pico 0, cae a -1 -> trail (0 - 1) = -1, igual que el final
    path = [0.0, -0.5, -1.0]
    assert simulate_trailing_exit(path, distance=1.0) == -1.0


def test_activation_blocks_trail_until_peak_reaches_threshold():
    # con activation=2, un pico de 1.5 no arma el trail -> devuelve el final
    path = [0.0, 1.5, 0.0]
    assert simulate_trailing_exit(path, distance=1.0, activation=2.0) == 0.0
    # con activation=0 (default), si arma: pico 1.5, cae a 0 (giveback 1.5>1) -> 0.5
    assert simulate_trailing_exit(path, distance=1.0, activation=0.0) == 0.5


def test_empty_path_is_safe():
    assert simulate_trailing_exit([], distance=1.0) == 0.0


def test_captures_winner_giveback_as_improvement():
    # trade que subio a 3 y devolvio todo a 0.2: trailing D=1 sale en 2 -> mejora
    paths = [[0.0, 3.0, 2.5, 1.0, 0.2]]
    comp = compare_trailing(paths, distances=[1.0])[0]
    assert comp.trades == 1
    assert comp.actual_avg_r == 0.2
    assert comp.policy_avg_r == 2.0   # 3 - 1
    assert comp.delta_avg_r == 1.8
    assert comp.improved == 1 and comp.hurt == 0


def test_counts_hurt_when_trailing_cuts_a_runner():
    # trade que tuvo un dip y despues siguio a 5: el trailing lo corta temprano (peor)
    paths = [[0.0, 1.5, 0.3, 2.0, 3.0, 4.0, 5.0]]  # dip de 1.5->0.3 (>1) corta en 0.5
    comp = compare_trailing(paths, distances=[1.0])[0]
    assert comp.actual_avg_r == 5.0
    assert comp.policy_avg_r == 0.5   # cortado en el dip temprano
    assert comp.hurt == 1 and comp.improved == 0


def test_compare_multiple_distances():
    paths = [[0.0, 2.0, 0.0], [0.0, 1.0, 3.0]]
    res = compare_trailing(paths, distances=[0.5, 1.0, 2.0])
    assert [r.distance for r in res] == [0.5, 1.0, 2.0]
    assert all(r.trades == 2 for r in res)


# ---------------------- captura + analisis con repo ---------------------- #
def test_record_open_trade_samples_skips_uncomputable_r():
    repo = _FakeRepo()
    opens = [
        _open(1, 100.0, 102.0, 99.0),   # r=+2
        _open(2, 100.0, 98.0, 99.0),    # r=-2
        _open(3, None, None, None),     # r None -> se salta
    ]
    n = record_open_trade_samples(repo, opens, "2026-06-09T00:00:00+00:00")
    assert n == 2 and len(repo.samples) == 2
    assert {s[0] for s in repo.samples} == {1, 2}


def test_analyze_closed_trades_builds_comparisons_from_paths():
    repo = _FakeRepo(closed=[_closed_forex(1, 103.0)], paths={1: [0.0, 3.0, 0.5]})
    comps = analyze_closed_trades(repo, [1.0], category="forex")
    assert comps[0].trades == 1
    assert comps[0].policy_avg_r == 2.0  # trailing corto en el giveback (3-1)


def test_analyze_skips_trades_without_enough_samples():
    repo = _FakeRepo(closed=[_closed_forex(1, 103.0)], paths={1: [0.0]})  # 1 muestra < 3
    comps = analyze_closed_trades(repo, [1.0], category="forex", min_samples=3)
    assert comps[0].trades == 0


# ----------------------- comando /exit_analysis -------------------------- #
def test_exit_analysis_command_off_message():
    bot = BasicTelegramAssistant(_settings(), _FakeRepo())  # flag off por default
    assert "apagado" in bot.handle("/exit_analysis")


def test_exit_analysis_command_with_data():
    repo = _FakeRepo(closed=[_closed_forex(1, 103.0)], paths={1: [0.0, 3.0, 0.5]})
    bot = BasicTelegramAssistant(replace(_settings(), enable_exit_shadow=True), repo)
    msg = bot.handle("/exit_analysis")
    assert "Exit analysis (forex)" in msg
    assert "trail D=1.0R" in msg
    assert "NO cambia ninguna salida" in msg or "no cambia ninguna salida" in msg
