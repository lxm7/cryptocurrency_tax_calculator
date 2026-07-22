"""Section 104 matching engine — behaviour tests (vertical TDD slices)."""

from datetime import date
from decimal import Decimal

from taxcalc.engine.matching import (
    Acquisition,
    Disposal,
    MatchRule,
    match_disposals,
)


def test_single_acquisition_then_full_disposal_matches_s104() -> None:
    """One buy, one later full sell: the disposal draws the whole pool at cost."""
    acqs = [
        Acquisition(
            date=date(2023, 1, 1),
            asset="BTC",
            quantity=Decimal("1"),
            cost_gbp=Decimal("20000"),
        )
    ]
    disps = [
        Disposal(
            date=date(2024, 1, 1),
            asset="BTC",
            quantity=Decimal("1"),
            proceeds_gbp=Decimal("30000"),
            fee_gbp=Decimal("0"),
        )
    ]

    outcome = match_disposals(acqs, disps)

    assert len(outcome.disposals) == 1
    result = outcome.disposals[0]
    assert [m.rule for m in result.matches] == [MatchRule.SECTION_104]
    assert result.matches[0].cost_gbp == Decimal("20000")
    assert result.gain_gbp == Decimal("10000")  # 30000 − 20000 − 0

    # pool fully consumed, carried forward at zero
    assert outcome.pools["BTC"].quantity == Decimal("0")
    assert outcome.pools["BTC"].cost_gbp == Decimal("0")
