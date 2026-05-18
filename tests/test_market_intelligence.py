from app.analyzers.news_analyzer import analyze_news
from app.analyzers.filing_analyzer import analyze_filings
from app.analyzers.pro_intelligence import analyze_professional_setup
from app.analyzers.technical_patterns import analyze_ohlcv
from app.collectors.news_collector import NewsItem
from app.collectors.sec_collector import SECFiling
from app.database.models import SecuritySummary, TokenSnapshot


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
    assert pattern.macd is not None
    assert pattern.relative_volume is not None
    assert pattern.sparkline


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


def test_filing_analyzer_detects_risk_filing() -> None:
    filings = [
        SECFiling(
            symbol="TEST",
            cik="0000000000",
            form="S-3",
            filing_date="2026-05-17",
            report_date="",
            accession_number="",
            primary_document="",
            description="Prospectus offering",
            url="",
        )
    ]

    label, score, reasons = analyze_filings(filings)

    assert label == "filing_risk"
    assert score < 0
    assert any("S-3" in reason for reason in reasons)


def test_professional_setup_combines_chart_news_and_filings() -> None:
    snapshot = TokenSnapshot(
        chain="stock",
        token_address="NVDA",
        category="stock",
        symbol="NVDA",
        price=100,
        volume_1h=100_000_000,
        price_change_24h=3,
    )
    candles = []
    for index in range(60):
        close = 100 + index * 0.4
        candles.append(
            {
                "open": close - 0.2,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 1_000 + index * 25,
            }
        )
    candles[-1]["close"] = 130
    candles[-1]["volume"] = 5_000
    pattern = analyze_ohlcv(candles)

    pro = analyze_professional_setup(
        snapshot,
        SecuritySummary(raw_summary="unknown"),
        pattern,
        news_label="positive_catalyst",
        news_score=24,
        filing_label="positive_filing_catalyst",
        filing_score=16,
    )

    assert pro.score > 30
    assert pro.bias in {"bullish", "neutral"}
    assert pro.reasons
