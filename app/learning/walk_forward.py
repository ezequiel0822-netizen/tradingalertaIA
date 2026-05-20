"""Walk-forward backtester: train/test split deslizante out-of-sample.

Detecta curve-fitting comparando metricas en train vs test windows.
NO tunea parametros (eso es Phase 6 strategy evolution).

Data source: paper_trades cerrados con strategy_name + alert_outcome_horizons
de las alertas vinculadas (status='final').
"""

import logging
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config.settings import Settings
from app.database.repository import Repository
from app.utils.time_utils import utc_now_iso


logger = logging.getLogger(__name__)


@dataclass
class WalkForwardWindow:
    strategy_name: str
    symbol: str | None
    category: str | None
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_sharpe: float
    train_win_rate: float
    train_avg_return: float
    test_sharpe: float
    test_win_rate: float
    test_avg_return: float
    degradation_pct: float
    train_samples: int
    test_samples: int


def _metrics(returns: list[float], wins: int, samples: int) -> tuple[float, float, float]:
    """Devuelve (sharpe_approx, win_rate, avg_return)."""
    if samples == 0 or not returns:
        return 0.0, 0.0, 0.0
    avg = sum(returns) / len(returns)
    win_rate = wins / samples if samples else 0.0
    if len(returns) >= 2:
        try:
            stdev = statistics.stdev(returns)
            sharpe = avg / stdev if stdev > 0 else 0.0
        except statistics.StatisticsError:
            sharpe = 0.0
    else:
        sharpe = 0.0
    return round(sharpe, 4), round(win_rate, 4), round(avg, 4)


def _slice_trades(
    trades: list[dict], start_iso: str, end_iso: str
) -> tuple[list[float], int, int]:
    """Filtra trades cerrados en la ventana. Retorna (returns, wins, samples)."""
    returns: list[float] = []
    wins = 0
    for t in trades:
        closed_at = str(t.get("closed_at") or "")
        if not closed_at:
            continue
        if not (start_iso <= closed_at < end_iso):
            continue
        r = t.get("unrealized_return_pct")
        if r is None:
            continue
        try:
            r_f = float(r)
        except (TypeError, ValueError):
            continue
        returns.append(r_f)
        if r_f > 0:
            wins += 1
    return returns, wins, len(returns)


class WalkForwardBacktester:
    def __init__(self, repository: Repository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings

    def run(
        self,
        strategy_name: str,
        category: str | None,
        start_iso: str,
        end_iso: str,
        train_days: int | None = None,
        test_days: int | None = None,
        slide_days: int | None = None,
    ) -> list[WalkForwardWindow]:
        """Corre walk-forward sobre paper_trades de una strategy."""
        train_days = train_days or self.settings.walk_forward_train_days
        test_days = test_days or self.settings.walk_forward_test_days
        slide_days = slide_days or self.settings.walk_forward_slide_days
        min_samples = self.settings.walk_forward_min_train_samples

        try:
            start = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
        except ValueError:
            return []

        # Fetch trades cerrados con strategy_name
        try:
            closed = self.repository.fetch_closed_trades_since(start.isoformat())
        except Exception:
            closed = []
        relevant = [
            t for t in closed
            if str(t.get("strategy_name") or "") == strategy_name
            and (category is None or str(t.get("category") or "") == category)
        ]

        windows: list[WalkForwardWindow] = []
        cursor = start
        while cursor + timedelta(days=train_days + test_days) <= end:
            train_start = cursor
            train_end = cursor + timedelta(days=train_days)
            test_start = train_end
            test_end = train_end + timedelta(days=test_days)

            train_returns, train_wins, train_n = _slice_trades(
                relevant, train_start.isoformat(), train_end.isoformat()
            )
            test_returns, test_wins, test_n = _slice_trades(
                relevant, test_start.isoformat(), test_end.isoformat()
            )

            if train_n < min_samples:
                cursor += timedelta(days=slide_days)
                continue

            train_sharpe, train_wr, train_avg = _metrics(train_returns, train_wins, train_n)
            test_sharpe, test_wr, test_avg = _metrics(test_returns, test_wins, test_n)

            if train_sharpe == 0 and test_sharpe == 0:
                degradation = 0.0
            elif train_sharpe == 0:
                degradation = 0.0
            else:
                degradation = round(
                    (train_sharpe - test_sharpe) / abs(train_sharpe) * 100, 2
                )

            window = WalkForwardWindow(
                strategy_name=strategy_name,
                symbol=None,
                category=category,
                train_start=train_start.isoformat(),
                train_end=train_end.isoformat(),
                test_start=test_start.isoformat(),
                test_end=test_end.isoformat(),
                train_sharpe=train_sharpe,
                train_win_rate=train_wr,
                train_avg_return=train_avg,
                test_sharpe=test_sharpe,
                test_win_rate=test_wr,
                test_avg_return=test_avg,
                degradation_pct=degradation,
                train_samples=train_n,
                test_samples=test_n,
            )
            windows.append(window)

            cursor += timedelta(days=slide_days)

        return windows

    def persist_windows(self, windows: list[WalkForwardWindow]) -> int:
        n = 0
        for w in windows:
            row = asdict(w)
            row["computed_at"] = utc_now_iso()
            try:
                if self.repository.insert_walk_forward_result(row):
                    n += 1
            except Exception:
                continue
        return n
