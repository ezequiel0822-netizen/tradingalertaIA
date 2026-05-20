"""Tests para Memecoin Hunter Pro analyzer."""

from datetime import datetime, timedelta, timezone

from app.analyzers.memecoin_hunter import analyze_memecoin
from app.database.models import SecuritySummary, TokenSnapshot
from tests.test_score import _settings


_NOW = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)


def _snap(
    pool_created_at: str | None,
    volume_5m: float = 0,
    volume_1h: float = 0,
    buys_5m: int = 0,
    is_boosted: bool = False,
) -> TokenSnapshot:
    return TokenSnapshot(
        chain="solana",
        token_address="ABC123",
        category="memecoin",
        symbol="MEME",
        name="Memecoin",
        price=0.0001,
        liquidity_usd=20000,
        volume_5m=volume_5m,
        volume_1h=volume_1h,
        buys_5m=buys_5m,
        is_boosted=is_boosted,
        pool_created_at=pool_created_at,
    )


def _safe_security() -> SecuritySummary:
    return SecuritySummary(
        honeypot_status="not_detected",
        contract_risk="ok",
        raw_summary='{"risks":[]}',
    )


def test_early_token_with_volume_gets_bonus() -> None:
    settings = _settings()
    created = (_NOW - timedelta(hours=2)).isoformat()
    snap = _snap(pool_created_at=created, volume_5m=2000, volume_1h=8000)

    result = analyze_memecoin(snap, _safe_security(), settings, now_utc=_NOW)

    assert result.is_early is True
    assert result.early_bonus >= 10  # 10 base
    assert result.anti_rug_multiplier == 1.0  # security ok
    assert any("Pool joven" in r for r in result.reasons)


def test_early_with_boost_gets_extra_bonus() -> None:
    settings = _settings()
    created = (_NOW - timedelta(hours=1)).isoformat()
    snap = _snap(pool_created_at=created, volume_5m=5000, volume_1h=12000, is_boosted=True)

    result = analyze_memecoin(snap, _safe_security(), settings, now_utc=_NOW)

    assert result.is_early is True
    assert result.early_bonus >= 15  # 10 base + 5 boost
    assert any("Boost" in r for r in result.reasons)


def test_volume_velocity_detected() -> None:
    settings = _settings()
    created = (_NOW - timedelta(hours=4)).isoformat()
    # vol_5m * 12 = 36000 vs vol_1h 10000 → ratio 3.6 (>2.0 default)
    snap = _snap(pool_created_at=created, volume_5m=3000, volume_1h=10000)

    result = analyze_memecoin(snap, _safe_security(), settings, now_utc=_NOW)

    assert result.volume_velocity_ratio is not None
    assert result.volume_velocity_ratio >= 2.0
    assert any("Aceleracion" in r for r in result.reasons)


def test_old_token_no_early_bonus() -> None:
    settings = _settings()
    created = (_NOW - timedelta(hours=48)).isoformat()
    snap = _snap(pool_created_at=created, volume_5m=2000, volume_1h=8000)

    result = analyze_memecoin(snap, _safe_security(), settings, now_utc=_NOW)

    assert result.is_early is False
    # Sin bonus por early, pero puede tener bonus por velocity si aplica
    assert result.age_hours == 48.0
    assert any("Pool maduro" in r for r in result.reasons)


def test_anti_rug_for_honeypot() -> None:
    settings = _settings()
    created = (_NOW - timedelta(hours=2)).isoformat()
    snap = _snap(pool_created_at=created, volume_5m=3000, volume_1h=10000)
    sec = SecuritySummary(honeypot_status="possible_honeypot", contract_risk="risky")

    result = analyze_memecoin(snap, sec, settings, now_utc=_NOW)

    # 0.5 (honeypot) * 0.7 (risky) = 0.35 → clamped a 0.3
    assert result.anti_rug_multiplier <= 0.5
    assert any("honeypot" in r.lower() for r in result.reasons)


def test_anti_rug_for_risky_contract_only() -> None:
    settings = _settings()
    created = (_NOW - timedelta(hours=2)).isoformat()
    snap = _snap(pool_created_at=created, volume_5m=3000, volume_1h=10000)
    sec = SecuritySummary(honeypot_status="not_detected", contract_risk="risky")

    result = analyze_memecoin(snap, sec, settings, now_utc=_NOW)

    assert abs(result.anti_rug_multiplier - 0.7) < 0.01
    assert any("risky" in r.lower() for r in result.reasons)


def test_no_pool_created_at_returns_no_age() -> None:
    settings = _settings()
    snap = _snap(pool_created_at=None, volume_5m=2000, volume_1h=8000)

    result = analyze_memecoin(snap, _safe_security(), settings, now_utc=_NOW)

    assert result.age_hours is None
    assert result.is_early is False  # sin edad no se considera early
