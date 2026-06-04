from app.analyzers.alert_decision_engine import should_send_alert
from app.database.models import EstimateResult
from tests.test_score import _settings


def _eligible_estimate() -> EstimateResult:
    return EstimateResult(
        estimated_gain_pct=600, estimated_loss_pct=40, confidence=80,
        label="high-conviction", reasons=[], eligible_for_gain_alert=True,
    )


def test_memecoin_blocked_by_default() -> None:
    settings = _settings()  # enable_memecoin_telegram=False
    assert should_send_alert(95, False, _eligible_estimate(), settings, "memecoin") is False


def test_memecoin_enabled_with_flag() -> None:
    base = _settings()
    settings = type(base)(**{**base.__dict__, "enable_memecoin_telegram": True})
    assert should_send_alert(95, False, _eligible_estimate(), settings, "memecoin") is True


def test_stock_alerts_still_pass_through() -> None:
    settings = _settings()
    assert should_send_alert(85, False, _eligible_estimate(), settings, "stock") is True


def test_stock_blocked_when_telegram_off() -> None:
    # v2.9.1: con enable_stock_telegram=False la accion NO va a Telegram...
    base = _settings()
    settings = type(base)(**{**base.__dict__, "enable_stock_telegram": False})
    assert should_send_alert(85, False, _eligible_estimate(), settings, "stock") is False


def test_memecoin_unaffected_by_stock_telegram_flag() -> None:
    # ...pero el flag de acciones no toca a las memecoins (control independiente).
    base = _settings()
    settings = type(base)(
        **{**base.__dict__, "enable_stock_telegram": False, "enable_memecoin_telegram": True}
    )
    assert should_send_alert(95, False, _eligible_estimate(), settings, "memecoin") is True
