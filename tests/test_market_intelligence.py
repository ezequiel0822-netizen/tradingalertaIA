from app.analyzers.news_analyzer import analyze_news
from app.analyzers.technical_patterns import analyze_ohlcv
from app.collectors.news_collector import NewsItem


def test_technical_pattern_detects_bullish_breakout() -> None:
    candles = []
    for index in range(60):
        close = 100 + index * 0.5
        candles.append(
            {
                "open": close - 0.2,
                "high": close + 0.4,
                "low": close - 0.4,
                "close": close,
                "volume": 1_000 + index * 20,
            }
        )
    candles[-1]["close"] = 140
    candles[-1]["volume"] = 5_000

    pattern = analyze_ohlcv(candles)

    assert pattern.score > 0
    assert pattern.label in {"bullish_breakout", "bullish_watch"}


def test_news_analyzer_detects_event_catalyst() -> None:
    items = [
        NewsItem(
            title="Company beats earnings and raises revenue guidance after conference call",
            link="https://example.com",
            published="",
        )
    ]

    label, score, reasons = analyze_news(items)

    assert label in {"positive_catalyst", "event_watch"}
    assert score > 0
    assert any("Eventos detectados" in reason for reason in reasons)
