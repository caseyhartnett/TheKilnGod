"""Unit tests for catch-up supervisor shadow decision logic."""

from __future__ import annotations

from thekilngod.oven import decide_catchup_shadow_state


def test_decide_state_prefers_holdoff() -> None:
    """Holdoff should always suppress actionable decisions."""
    state = decide_catchup_shadow_state(
        avg_error_confidence=120.0,
        rise_rate_trend=0.0,
        duty_cycle_confidence_pct=100.0,
        lagging_seconds=7200.0,
        cusum_deg_seconds=200000.0,
        holdoff_active=True,
    )
    assert state == "holdoff"


def test_decide_state_would_abort_for_sustained_stall() -> None:
    """Large sustained lag with high duty and no rise should mark would_abort."""
    state = decide_catchup_shadow_state(
        avg_error_confidence=85.0,
        rise_rate_trend=0.0,
        duty_cycle_confidence_pct=98.0,
        lagging_seconds=3600.0,
        cusum_deg_seconds=120000.0,
        holdoff_active=False,
    )
    assert state == "would_abort"


def test_decide_state_would_extend_when_lagging_but_rising() -> None:
    """Lag plus positive trend should mark would_extend."""
    state = decide_catchup_shadow_state(
        avg_error_confidence=65.0,
        rise_rate_trend=40.0,
        duty_cycle_confidence_pct=75.0,
        lagging_seconds=1200.0,
        cusum_deg_seconds=10000.0,
        holdoff_active=False,
    )
    assert state == "would_extend"
