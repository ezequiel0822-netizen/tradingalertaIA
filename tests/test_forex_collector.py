from unittest.mock import MagicMock, patch

from app.analyzers.alert_decision_engine import (
    candidate_for_security_check,
    should_send_alert,
)
from app.collectors.forex_collector import ForexCollector, _classify
from app.database.models import EstimateResult, TokenSnapshot
from tests.test_score import _settings


def _enable_forex(base):
    return type(base)(
        **{
            **base.__dict__,
            "enable_forex_collector": True,
            "forex_symbols": ["eurusd=x", "gc=f"],
        }
    )


def _yahoo_payload(symbol: str, last_close: float) -> dict:
    closes = [last_close * (1 + 0.001 * i) for i in range(-30, 0)]
    closes.append(last_close)
    highs = [c * 1.001 for c in closes]
    lows = [c * 0.999 for c in closes]
    return {
        "chart": {
            "result": [
                {
                    "meta": {"regularMarketPrice": last_close, "shortName": symbol},
                    "timestamp": list(range(len(closes))),
                    "indicators": {
                        "quote": [
                            {
                                "open": closes,
                                "high": highs,
                                "low": lows,
                                "close": closes,
                                "volume": [0] * len(closes),
                            }
                        ]
                    },
                }
            ]
        }
    }


def test_forex_collector_disabled_returns_empty() -> None:
    settings = _settings()  # enable_forex_collector=False in test helper
    collector = ForexCollector(settings)
    assert collector.collect() == []


def test_classify_forex_and_gold() -> None:
    assert _classify("EURUSD=X") == ("forex", "forex", "FOREX_MOVEMENT")
    assert _classify("GC=F") == ("gold", "commodity", "GOLD_MOVEMENT")
    assert _classify("XAUUSD=X") == ("gold", "commodity", "GOLD_MOVEMENT")


def test_forex_collector_parses_eurusd() -> None:
    settings = _enable_forex(_settings())
    settings = type(settings)(
        **{**settings.__dict__, "forex_symbols": ["eurusd=x"]}
    )
    collector = ForexCollector(settings)

    mock_response = MagicMock()
    mock_response.json.return_value = _yahoo_payload("EURUSD=X", 1.0850)
    mock_response.raise_for_status = MagicMock()

    with patch.object(collector.session, "get", return_value=mock_response):
        snapshots = collector.collect()

    assert len(snapshots) == 1
    snap = snapshots[0]
    assert snap.category == "forex"
    assert snap.chain == "forex"
    assert snap.symbol == "EURUSD=X"
    assert abs(snap.price - 1.0850) < 1e-6
    assert snap.liquidity_usd is None
    assert snap.event_type == "FOREX_MOVEMENT"


def test_forex_collector_parses_gold_future() -> None:
    settings = _enable_forex(_settings())
    settings = type(settings)(**{**settings.__dict__, "forex_symbols": ["gc=f"]})
    collector = ForexCollector(settings)

    mock_response = MagicMock()
    mock_response.json.return_value = _yahoo_payload("GC=F", 2400.0)
    mock_response.raise_for_status = MagicMock()

    with patch.object(collector.session, "get", return_value=mock_response):
        snapshots = collector.collect()

    assert len(snapshots) == 1
    snap = snapshots[0]
    assert snap.category == "gold"
    assert snap.chain == "commodity"
    assert snap.event_type == "GOLD_MOVEMENT"


def test_forex_snapshot_does_not_send_alert() -> None:
    settings = _settings()
    estimate = EstimateResult(
        estimated_gain_pct=10,
        estimated_loss_pct=3,
        confidence=80,
        label="high",
        reasons=[],
        eligible_for_gain_alert=True,
    )

    assert should_send_alert(85, False, estimate, settings, "forex") is False
    assert should_send_alert(85, False, estimate, settings, "gold") is False


def test_forex_does_not_trigger_security_check() -> None:
    settings = _settings()
    forex_snap = TokenSnapshot(
        chain="forex",
        token_address="EURUSD=X",
        category="forex",
        symbol="EURUSD=X",
        event_type="FOREX_MOVEMENT",
        liquidity_usd=1_000_000_000,
        volume_1h=999_999_999,
    )
    gold_snap = TokenSnapshot(
        chain="commodity",
        token_address="GC=F",
        category="gold",
        symbol="GC=F",
        event_type="GOLD_MOVEMENT",
        liquidity_usd=1_000_000_000,
    )

    assert candidate_for_security_check(forex_snap, settings) is False
    assert candidate_for_security_check(gold_snap, settings) is False
