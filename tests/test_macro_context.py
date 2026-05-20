from datetime import datetime, timezone

from app.intelligence.macro_context import current_session, is_in_session


def _at(hour: int) -> datetime:
    return datetime(2026, 1, 15, hour, 0, 0, tzinfo=timezone.utc)


def test_asian_only_at_03_00() -> None:
    ctx = current_session(_at(3))
    assert ctx["asian"] is True
    assert ctx["london"] is False
    assert ctx["ny"] is False
    assert ctx["active_sessions"] == ["asian"]
    assert ctx["is_high_liquidity"] is False


def test_london_only_at_10_00() -> None:
    ctx = current_session(_at(10))
    assert ctx["asian"] is False
    assert ctx["london"] is True
    assert ctx["ny"] is False
    assert ctx["active_sessions"] == ["london"]


def test_ny_only_at_20_00() -> None:
    ctx = current_session(_at(20))
    assert ctx["asian"] is False
    assert ctx["london"] is False
    assert ctx["ny"] is True


def test_london_ny_overlap_high_liquidity_at_15_00() -> None:
    ctx = current_session(_at(15))
    assert ctx["london"] is True
    assert ctx["ny"] is True
    assert ctx["is_high_liquidity"] is True
    assert "london" in ctx["active_sessions"]
    assert "ny" in ctx["active_sessions"]


def test_returns_dict_shape() -> None:
    ctx = current_session(_at(12))
    expected_keys = {"asian", "london", "ny", "active_sessions", "is_high_liquidity", "utc_hour"}
    assert expected_keys.issubset(ctx.keys())
    assert is_in_session("london", _at(10)) is True
    assert is_in_session("asian", _at(10)) is False
