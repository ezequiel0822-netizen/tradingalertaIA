"""Tests para alertas forex/gold con learning gate (Phase 3)."""

from app.analyzers.alert_decision_engine import should_send_alert
from app.database.models import EstimateResult
from tests.test_score import _settings


def _eligible() -> EstimateResult:
    return EstimateResult(
        estimated_gain_pct=2.5, estimated_loss_pct=1.0, confidence=70,
        label="forex_setup", reasons=[], eligible_for_gain_alert=True,
    )


def test_forex_blocked_when_setting_disabled() -> None:
    settings = _settings()  # enable_forex_alerts=False por default
    assert should_send_alert(80, False, _eligible(), settings, "forex") is False


def test_gold_blocked_when_setting_disabled() -> None:
    settings = _settings()  # enable_gold_alerts=False por default
    assert should_send_alert(80, False, _eligible(), settings, "gold") is False


def test_forex_allowed_when_setting_enabled() -> None:
    base = _settings()
    settings = type(base)(**{**base.__dict__, "enable_forex_alerts": True})
    assert should_send_alert(80, False, _eligible(), settings, "forex") is True


def test_gold_allowed_when_setting_enabled() -> None:
    base = _settings()
    settings = type(base)(**{**base.__dict__, "enable_gold_alerts": True})
    assert should_send_alert(80, False, _eligible(), settings, "gold") is True
