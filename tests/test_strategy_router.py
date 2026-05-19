from dataclasses import dataclass, field
from types import SimpleNamespace

from app.database.models import TokenSnapshot
from app.strategies.base import StrategyContext, StrategySignal
from app.strategies.breakout import BreakoutStrategy
from app.strategies.mean_reversion import MeanReversionStrategy
from app.strategies.momentum import MomentumStrategy
from app.strategies.news_catalyst import NewsCatalystStrategy
from app.strategies.strategy_router import StrategyRouter
from tests.test_score import _settings


def _stock_snapshot(price: float = 100.0, category: str = "stock") -> TokenSnapshot:
    return TokenSnapshot(
        chain=category, token_address="NVDA", category=category,
        symbol="NVDA", price=price, liquidity_usd=1_000_000,
    )


def _pattern(**kwargs):
    defaults = dict(
        label="neutral", score=70, rsi=55, trend="neutral",
        macd=0.0, macd_signal=0.0, atr_pct=2.0, relative_volume=1.2,
        reasons=[],
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _ctx(snapshot=None, pattern=None, news_score=0, news_label="no_recent_news", pro=None) -> StrategyContext:
    return StrategyContext(
        snapshot=snapshot or _stock_snapshot(),
        candles=[],
        pattern=pattern,
        pro=pro,
        news_label=news_label,
        news_score=news_score,
        macro={"is_high_liquidity": True},
    )


def test_breakout_fires_when_conditions_met() -> None:
    settings = _settings()
    pat = _pattern(label="bullish_breakout", score=80, rsi=65, trend="bullish",
                   atr_pct=3.0, relative_volume=2.5)
    sig = BreakoutStrategy().evaluate(_ctx(pattern=pat), settings)
    assert sig is not None
    assert sig.direction == "long"
    assert sig.confidence >= 60
    assert sig.entry == 100.0


def test_breakout_skips_when_volume_low() -> None:
    settings = _settings()
    pat = _pattern(label="bullish_breakout", score=80, rsi=65, trend="bullish",
                   atr_pct=3.0, relative_volume=1.5)
    sig = BreakoutStrategy().evaluate(_ctx(pattern=pat), settings)
    assert sig is None


def test_mean_reversion_fires_oversold_long() -> None:
    settings = _settings()
    pat = _pattern(label="neutral", rsi=24, atr_pct=2.0)
    sig = MeanReversionStrategy().evaluate(_ctx(pattern=pat), settings)
    assert sig is not None
    assert sig.direction == "long"


def test_mean_reversion_fires_overbought_short() -> None:
    settings = _settings()
    pat = _pattern(label="neutral", rsi=78, atr_pct=2.0)
    sig = MeanReversionStrategy().evaluate(_ctx(pattern=pat), settings)
    assert sig is not None
    assert sig.direction == "short"


def test_momentum_fires_macd_bullish() -> None:
    settings = _settings()
    pat = _pattern(trend="bullish", rsi=60, macd=0.5, macd_signal=0.2, score=75, atr_pct=2.0)
    sig = MomentumStrategy().evaluate(_ctx(pattern=pat), settings)
    assert sig is not None
    assert sig.direction == "long"


def test_news_catalyst_fires_with_high_news_score() -> None:
    settings = _settings()
    pat = _pattern(trend="bullish", relative_volume=2.0, atr_pct=2.5)
    sig = NewsCatalystStrategy().evaluate(
        _ctx(pattern=pat, news_score=30, news_label="positive_catalyst"),
        settings,
    )
    assert sig is not None
    assert sig.direction == "long"


def test_news_catalyst_skips_non_stock() -> None:
    settings = _settings()
    snap = TokenSnapshot(
        chain="solana", token_address="MEME", category="memecoin",
        symbol="MEME", price=0.001,
    )
    pat = _pattern(trend="bullish", relative_volume=2.0, atr_pct=2.5)
    sig = NewsCatalystStrategy().evaluate(
        _ctx(snapshot=snap, pattern=pat, news_score=30),
        settings,
    )
    assert sig is None


def test_router_respects_min_confidence_filter() -> None:
    base = _settings()
    settings = type(base)(**{**base.__dict__, "strategy_min_confidence": 95})
    pat = _pattern(label="bullish_breakout", score=70, rsi=65, trend="bullish",
                   atr_pct=2.0, relative_volume=2.0)
    router = StrategyRouter(settings)
    signals = router.route(_ctx(pattern=pat), settings)
    # confidence ~ 60 + 10 + 17 = 87, below 95
    assert signals == []


def test_router_skips_disabled_strategies_and_handles_exceptions() -> None:
    base = _settings()
    settings = type(base)(
        **{
            **base.__dict__,
            "enable_strategy_breakout": False,
            "enable_strategy_mean_reversion": False,
            "enable_strategy_momentum": False,
            "enable_strategy_news_catalyst": False,
        }
    )
    router = StrategyRouter(settings)
    assert router.strategies == []
    signals = router.route(_ctx(pattern=_pattern()), settings)
    assert signals == []
