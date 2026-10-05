"""v3.13.2 — alertas de forex/oro: estimador propio, envío solo con movimiento notable,
título por mercado y textos de Telegram sin memecoins cuando el motor está apagado.

Reproduce la captura del user (2026-10-05): "TOP MEMECOINS" con EURUSD/USDCAD,
"Caída est.: 90.01%", confianza 25 y score 21.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from app.alerts.alert_formatter import format_grouped_telegram_alert
from app.analyzers.alert_decision_engine import should_send_alert
from app.analyzers.move_estimator import estimate_move
from app.assistant.command_handler import BasicTelegramAssistant
from app.database.db import init_db
from app.database.models import AlertRecord, EstimateResult, SecuritySummary, TokenSnapshot
from app.database.repository import Repository
from tests.test_score import _settings


def _repo() -> Repository:
    db_dir = Path.cwd() / ".test_dbs"
    db_dir.mkdir(exist_ok=True)
    db_path = db_dir / f"fx_v3132_{uuid4().hex}.db"
    init_db(db_path)
    return Repository(db_path)


def _fx(symbol="EURUSD=X", category="forex", ch1=0.02, ch24=-0.10, price=1.12345) -> TokenSnapshot:
    return TokenSnapshot(
        chain="forex" if category == "forex" else "commodity", token_address=symbol,
        category=category, symbol=symbol, name=symbol, source="Yahoo Finance",
        event_type="FOREX_MOVEMENT" if category == "forex" else "GOLD_MOVEMENT",
        price=price, liquidity_usd=None, volume_5m=None, volume_1h=None, volume_24h=None,
        price_change_5m=0.01, price_change_1h=ch1, price_change_24h=ch24,
    )


def _est(snapshot: TokenSnapshot) -> EstimateResult:
    return estimate_move(snapshot, SecuritySummary(raw_summary="unknown"), 21, _settings())


# -------------------------------------------------------------- estimador
def test_fx_no_longer_gets_memecoin_estimate() -> None:
    e = _est(_fx())
    assert e.estimated_loss_pct == 0.0 and e.estimated_gain_pct == 0.0   # antes: 90.01 / 0
    assert e.eligible_for_gain_alert is False
    assert e.confidence == 75                                         # datos completos
    assert any("Movimiento 1h: +0.02%" in r for r in e.reasons)
    assert any("no estima" in r for r in e.reasons)


def test_fx_notable_move_thresholds_forex_and_gold() -> None:
    assert _est(_fx(ch1=0.6, ch24=0.0)).eligible_for_gain_alert is True
    assert _est(_fx(ch1=0.0, ch24=-1.6)).eligible_for_gain_alert is True
    assert _est(_fx(ch1=0.49, ch24=1.49)).eligible_for_gain_alert is False
    gold = dict(symbol="GC=F", category="gold")
    assert _est(_fx(ch1=0.8, ch24=2.0, **gold)).eligible_for_gain_alert is False   # normal para oro
    assert _est(_fx(ch1=1.1, ch24=0.0, **gold)).eligible_for_gain_alert is True
    assert _est(_fx(ch1=0.6)).reasons[0] == "Movimiento notable para un par de divisas."
    assert _est(_fx(ch1=1.1, **gold)).reasons[0] == "Movimiento notable para el oro."


def test_fx_missing_changes_lower_confidence_not_crash() -> None:
    e = _est(_fx(ch1=None, ch24=None))
    assert e.eligible_for_gain_alert is False and e.confidence == 45


# ------------------------------------------------------------ envío
def test_fx_routine_snapshot_is_not_sent_even_with_alerts_on() -> None:
    s = replace(_settings(), enable_forex_alerts=True, enable_gold_alerts=True)
    assert should_send_alert(21, False, _est(_fx()), s, "forex") is False          # el bug
    assert should_send_alert(21, False, _est(_fx(ch1=0.7)), s, "forex") is True
    assert should_send_alert(21, False, _est(_fx(symbol="GC=F", category="gold")), s, "gold") is False


# --------------------------------------------------------- formato
def _record(snapshot: TokenSnapshot) -> AlertRecord:
    return AlertRecord(
        token_id=1, alert_type=snapshot.event_type, snapshot=snapshot, app_version="v3.13.2",
        category=snapshot.category, score=21, risk_level="low", reasons=_est(snapshot).reasons,
        security=SecuritySummary(raw_summary="unknown"), estimate=_est(snapshot),
    )


def test_grouped_title_per_market_and_observed_move_for_fx() -> None:
    msg = format_grouped_telegram_alert([_record(_fx(ch1=0.62))], "forex", "v3.13.2")
    assert "TOP FOREX" in msg and "MEMECOINS" not in msg
    assert "Mov. 1h: +0.62% | 24h: -0.10%" in msg
    assert "Caída est." not in msg and "90.01" not in msg
    assert "Score:" not in msg and "Confianza:" not in msg     # fórmulas de memecoin
    assert "Precio: 1.12345" in msg
    gold = format_grouped_telegram_alert(
        [_record(_fx(symbol="GC=F", category="gold", ch1=1.2, price=4170.8))], "gold", "v3.13.2")
    assert "TOP ORO" in gold and "Precio: $4,170.80" in gold
    stock = format_grouped_telegram_alert([], "stock", "v3.13.2")
    assert "TOP BOLSA" in stock


# ------------------------------------------------------- comandos
def _assistant(**overrides) -> tuple[BasicTelegramAssistant, Repository]:
    repo = _repo()
    return BasicTelegramAssistant(replace(_settings(), **overrides), repo), repo


def test_status_cupos_help_without_memecoins_when_engine_off() -> None:
    a, _ = _assistant(enable_memecoin_engine=False, enable_forex_alerts=True,
                      enable_mt5_demo_trading=True, enable_auto_confirm_demo=True,
                      enable_ai_agent=True)
    status, cupos, help_, config = (a.handle("/status"), a.handle("/cupos"),
                                     a.handle("/help"), a.handle("/config"))
    for text in (status, cupos):
        assert "Memecoin" not in text
        assert "Bolsa" in text and "Forex" in text and "Oro" not in text
    assert "read-only" not in status
    assert "solo MT5 DEMO (auto) | Agente IA: encendido" in status
    assert "/top_memecoins" not in help_ and "requieren confirmacion manual" not in help_
    assert "motor apagado" in config and "Cupo memecoins" not in config
    assert "Alertas oro: apagadas" in config


def test_memecoins_still_listed_when_engine_on() -> None:
    a, _ = _assistant(enable_memecoin_engine=True)
    assert "Memecoins" in a.handle("/cupos") and "/top_memecoins" in a.handle("/help")


def test_top_is_honest_about_fx_and_analyze_fx_has_no_fake_estimate() -> None:
    a, repo = _assistant(enable_memecoin_engine=False)
    snap = _fx()
    repo.upsert_token(snap, score=21, risk_level="low", estimate=_est(snap))
    top = a.handle("/top")
    assert "Forex/oro: sin ranking" in top and "/agente" in top
    assert "EURUSD" not in top and "Memecoins" not in top     # sin "top" arbitrario
    analysis = a.handle("/analiza EURUSD=X")
    assert "no estima subidas/caidas" in analysis
    assert "Caida estimada" not in analysis and "Score" not in analysis


def test_discard_reason_for_fx_is_not_the_memecoin_threshold() -> None:
    a, repo = _assistant()
    snap = _fx()
    token_id = repo.upsert_token(snap, score=21, risk_level="low", estimate=_est(snap))
    repo.insert_alert(AlertRecord(
        token_id=token_id, alert_type="FOREX_MOVEMENT", snapshot=snap, app_version="v3.13.2",
        category="forex", score=21, risk_level="low", reasons=["x"],
        security=SecuritySummary(raw_summary="unknown"), estimate=_est(snap),
        sent_to_telegram=False))
    text = a.handle("/descartes")
    assert "sin movimiento notable" in text and "subida minima" not in text
