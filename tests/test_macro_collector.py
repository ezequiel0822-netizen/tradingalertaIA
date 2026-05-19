"""Tests para MacroCollector con mocks de Yahoo."""

from unittest.mock import MagicMock, patch

from app.collectors.macro_collector import MacroCollector, classify_regime
from tests.test_score import _settings


def _enable_macro(base):
    return type(base)(**{**base.__dict__, "enable_macro_collector": True})


def _yahoo_response(price: float, prev: float | None = None) -> dict:
    closes = [prev] if prev is not None else []
    closes.append(price)
    return {
        "chart": {
            "result": [
                {
                    "meta": {"regularMarketPrice": price},
                    "indicators": {"quote": [{"close": closes}]},
                }
            ]
        }
    }


def test_classify_regime_logic() -> None:
    assert classify_regime(15.0, 0.1) == "risk_on"
    assert classify_regime(28.0, 0.0) == "risk_off"
    assert classify_regime(22.0, 1.0) == "risk_off"
    assert classify_regime(20.0, 0.0) == "neutral"
    assert classify_regime(None, None) == "neutral"


def test_macro_disabled_returns_none() -> None:
    settings = _settings()  # enable_macro_collector=False
    c = MacroCollector(settings)
    assert c.collect() is None


def test_macro_fetches_three_symbols(monkeypatch) -> None:
    settings = _enable_macro(_settings())
    c = MacroCollector(settings)

    def fake_get(url, **kwargs):
        if "VIX" in url:
            data = _yahoo_response(15.5)
        elif "DX-Y" in url:
            data = _yahoo_response(104.0, prev=103.5)
        else:  # SPY
            data = _yahoo_response(550.0)
        response = MagicMock()
        response.json.return_value = data
        response.raise_for_status = MagicMock()
        return response

    with patch.object(c.session, "get", side_effect=fake_get):
        result = c.collect()

    assert result is not None
    assert result["vix_value"] == 15.5
    assert result["dxy_value"] == 104.0
    assert result["spy_value"] == 550.0
    assert result["regime"] in {"risk_on", "neutral", "risk_off"}
