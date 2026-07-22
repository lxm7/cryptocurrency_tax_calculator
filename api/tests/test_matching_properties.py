"""Section 104 matching engine — property-based invariants (Hypothesis).

These assert properties that must hold for *every* valid input, not one hand-
picked example: the engine is order-independent (batch semantics) and conserves
both quantity and cost. Conservation is the strongest correctness signal we can
give without HMRC worked numbers; determinism underpins a reproducible audit trail.

Decimal-only generation, bounded to keep same-day collisions and 30-day-window
overlaps dense so the contended paths are actually exercised.
"""

from __future__ import annotations

import datetime as dt
from fractions import Fraction

from hypothesis import given, settings
from hypothesis import strategies as st

from taxcalc.engine.matching import (
    Acquisition,
    Disposal,
    MatchRule,
    match_disposals,
)

# Engine money/quantity are exact Fraction; sum accumulators must match (Decimal +
# Fraction raises TypeError), and Fraction(Decimal(...)) is an exact conversion.
_ZERO = Fraction(0)

# A short date span over few assets → dense same-day and 30-day contention.
_ASSETS = ["BTC", "ETH", "SOL"]
_DATES = st.dates(min_value=dt.date(2023, 1, 1), max_value=dt.date(2023, 4, 30))
_DEC = dict(places=2, allow_nan=False, allow_infinity=False)
_QTY = st.decimals(min_value="0.01", max_value="100", **_DEC)
_MONEY = st.decimals(min_value="0", max_value="1000000", **_DEC)
_FEE = st.decimals(min_value="0", max_value="1000", **_DEC)

_ACQUISITION = st.builds(
    Acquisition, date=_DATES, asset=st.sampled_from(_ASSETS), quantity=_QTY, cost_gbp=_MONEY
)
_DISPOSAL = st.builds(
    Disposal,
    date=_DATES,
    asset=st.sampled_from(_ASSETS),
    quantity=_QTY,
    proceeds_gbp=_MONEY,
    fee_gbp=_FEE,
)
_ACQS = st.lists(_ACQUISITION, max_size=8)
_DISPS = st.lists(_DISPOSAL, max_size=8)


def _assets_in(acqs: list[Acquisition], disps: list[Disposal]) -> set[str]:
    return {a.asset for a in acqs} | {d.asset for d in disps}


@settings(max_examples=300)
@given(data=st.data())
def test_result_is_independent_of_input_order(data: st.DataObject) -> None:
    """Batch semantics: shuffling the acquisition and disposal lists must yield a
    byte-identical MatchOutcome (the engine sorts internally)."""
    acqs = data.draw(_ACQS)
    disps = data.draw(_DISPS)
    acqs_shuffled = data.draw(st.permutations(acqs))
    disps_shuffled = data.draw(st.permutations(disps))

    assert match_disposals(acqs, disps) == match_disposals(acqs_shuffled, disps_shuffled)


@given(acqs=_ACQS, disps=_DISPS)
def test_cost_is_conserved(acqs: list[Acquisition], disps: list[Disposal]) -> None:
    """Every acquisition's cost lands in exactly one place — a real match or the
    carried-forward pool. SECTION_104_SHORT chunks are nil-cost and back no
    acquisition, so they are excluded from the ledger."""
    outcome = match_disposals(acqs, disps)

    for asset in _assets_in(acqs, disps):
        acquired = sum((Fraction(a.cost_gbp) for a in acqs if a.asset == asset), _ZERO)
        matched = sum(
            (
                m.cost_gbp
                for r in outcome.disposals
                if r.disposal.asset == asset
                for m in r.matches
                if m.rule is not MatchRule.SECTION_104_SHORT
            ),
            _ZERO,
        )
        assert matched + outcome.pools[asset].cost_gbp == acquired


@given(acqs=_ACQS, disps=_DISPS)
def test_quantity_is_conserved(acqs: list[Acquisition], disps: list[Disposal]) -> None:
    """Every disposal is fully accounted for (matches, incl. any short chunk, sum
    to its quantity), and on the acquisition side non-short matched quantity plus
    the carried-forward pool equals everything acquired."""
    outcome = match_disposals(acqs, disps)

    for r in outcome.disposals:
        assert sum((m.quantity for m in r.matches), _ZERO) == Fraction(r.disposal.quantity)

    for asset in _assets_in(acqs, disps):
        acquired = sum((Fraction(a.quantity) for a in acqs if a.asset == asset), _ZERO)
        matched = sum(
            (
                m.quantity
                for r in outcome.disposals
                if r.disposal.asset == asset
                for m in r.matches
                if m.rule is not MatchRule.SECTION_104_SHORT
            ),
            _ZERO,
        )
        assert matched + outcome.pools[asset].quantity == acquired
