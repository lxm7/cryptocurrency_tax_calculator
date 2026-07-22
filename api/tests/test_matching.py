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


def test_partial_disposal_draws_averaged_cost_and_carries_remainder() -> None:
    """One buy, a later partial sell: cost apportions by quantity, pool carries the rest."""
    acqs = [
        Acquisition(
            date=date(2023, 1, 1),
            asset="BTC",
            quantity=Decimal("2"),
            cost_gbp=Decimal("30000"),  # 15000 / BTC
        )
    ]
    disps = [
        Disposal(
            date=date(2024, 1, 1),
            asset="BTC",
            quantity=Decimal("1"),
            proceeds_gbp=Decimal("20000"),
            fee_gbp=Decimal("0"),
        )
    ]

    outcome = match_disposals(acqs, disps)

    result = outcome.disposals[0]
    assert [m.rule for m in result.matches] == [MatchRule.SECTION_104]
    assert result.matches[0].quantity == Decimal("1")
    assert result.matches[0].cost_gbp == Decimal("15000")  # half the pooled cost
    assert result.gain_gbp == Decimal("5000")  # 20000 − 15000 − 0

    # remainder carried forward: 1 BTC at the untouched half of the cost
    assert outcome.pools["BTC"].quantity == Decimal("1")
    assert outcome.pools["BTC"].cost_gbp == Decimal("15000")


def test_conservation_holds_under_indivisible_apportionment() -> None:
    """A recurring-decimal split must still conserve cost: matched + carryforward == original."""
    acqs = [
        Acquisition(
            date=date(2023, 1, 1),
            asset="BTC",
            quantity=Decimal("3"),
            cost_gbp=Decimal("10000"),  # 1/3 splits do not terminate
        )
    ]
    disps = [
        Disposal(
            date=date(2024, 1, 1),
            asset="BTC",
            quantity=Decimal("1"),
            proceeds_gbp=Decimal("5000"),
            fee_gbp=Decimal("0"),
        )
    ]

    outcome = match_disposals(acqs, disps)

    matched_cost = outcome.disposals[0].allowable_cost_gbp
    carried_cost = outcome.pools["BTC"].cost_gbp
    assert matched_cost + carried_cost == Decimal("10000")
    assert outcome.pools["BTC"].quantity == Decimal("2")


def test_multiple_buys_blend_into_one_averaged_pool() -> None:
    """Two buys at different prices average into a single pool the disposal draws from."""
    acqs = [
        Acquisition(
            date=date(2023, 1, 1),
            asset="BTC",
            quantity=Decimal("1"),
            cost_gbp=Decimal("10000"),
        ),
        Acquisition(
            date=date(2023, 6, 1),
            asset="BTC",
            quantity=Decimal("3"),
            cost_gbp=Decimal("30000"),
        ),
    ]  # pool: 4 BTC / 40000 GBP → 10000 per BTC
    disps = [
        Disposal(
            date=date(2024, 1, 1),
            asset="BTC",
            quantity=Decimal("2"),
            proceeds_gbp=Decimal("25000"),
            fee_gbp=Decimal("0"),
        )
    ]

    outcome = match_disposals(acqs, disps)

    result = outcome.disposals[0]
    assert [m.rule for m in result.matches] == [MatchRule.SECTION_104]
    assert result.matches[0].cost_gbp == Decimal("20000")  # 2 * averaged 10000
    assert result.gain_gbp == Decimal("5000")  # 25000 − 20000 − 0

    assert outcome.pools["BTC"].quantity == Decimal("2")
    assert outcome.pools["BTC"].cost_gbp == Decimal("20000")


def test_same_day_acquisition_matches_before_pool_at_own_cost() -> None:
    """An acquisition on the disposal's own day is matched first, at its own cost,
    leaving the pre-existing s104 pool untouched."""
    acqs = [
        Acquisition(
            date=date(2023, 1, 1),
            asset="BTC",
            quantity=Decimal("1"),
            cost_gbp=Decimal("10000"),  # into the pool
        ),
        Acquisition(
            date=date(2024, 6, 1),
            asset="BTC",
            quantity=Decimal("1"),
            cost_gbp=Decimal("20000"),  # same day as the disposal
        ),
    ]
    disps = [
        Disposal(
            date=date(2024, 6, 1),
            asset="BTC",
            quantity=Decimal("1"),
            proceeds_gbp=Decimal("25000"),
            fee_gbp=Decimal("0"),
        )
    ]

    outcome = match_disposals(acqs, disps)

    result = outcome.disposals[0]
    assert [m.rule for m in result.matches] == [MatchRule.SAME_DAY]
    assert result.matches[0].cost_gbp == Decimal("20000")  # own cost, not blended 15000
    assert result.gain_gbp == Decimal("5000")  # 25000 − 20000 − 0

    # original acquisition survives untouched in the pool
    assert outcome.pools["BTC"].quantity == Decimal("1")
    assert outcome.pools["BTC"].cost_gbp == Decimal("10000")


def test_same_day_acquisitions_pool_and_excess_falls_to_s104() -> None:
    """Multiple same-day buys combine to one averaged acquisition; the part not
    disposed of that day drops into the s104 pool."""
    acqs = [
        Acquisition(
            date=date(2024, 6, 1),
            asset="BTC",
            quantity=Decimal("1"),
            cost_gbp=Decimal("15000"),
        ),
        Acquisition(
            date=date(2024, 6, 1),
            asset="BTC",
            quantity=Decimal("1"),
            cost_gbp=Decimal("25000"),
        ),
    ]  # same-day combined: 2 BTC / 40000 → 20000 per BTC
    disps = [
        Disposal(
            date=date(2024, 6, 1),
            asset="BTC",
            quantity=Decimal("1"),
            proceeds_gbp=Decimal("25000"),
            fee_gbp=Decimal("0"),
        )
    ]

    outcome = match_disposals(acqs, disps)

    result = outcome.disposals[0]
    assert [m.rule for m in result.matches] == [MatchRule.SAME_DAY]
    assert result.matches[0].cost_gbp == Decimal("20000")  # combined same-day average
    assert result.gain_gbp == Decimal("5000")

    # the undisposed 1 BTC of same-day stock carries forward at the same-day average
    assert outcome.pools["BTC"].quantity == Decimal("1")
    assert outcome.pools["BTC"].cost_gbp == Decimal("20000")


def test_disposal_spills_from_same_day_into_s104() -> None:
    """A disposal larger than the same-day acquisition matches same-day first, then
    draws the remainder from the pool — matches reported in priority order."""
    acqs = [
        Acquisition(
            date=date(2023, 1, 1),
            asset="BTC",
            quantity=Decimal("2"),
            cost_gbp=Decimal("20000"),  # pool: 10000 per BTC
        ),
        Acquisition(
            date=date(2024, 6, 1),
            asset="BTC",
            quantity=Decimal("1"),
            cost_gbp=Decimal("30000"),  # same day as the disposal
        ),
    ]
    disps = [
        Disposal(
            date=date(2024, 6, 1),
            asset="BTC",
            quantity=Decimal("2"),
            proceeds_gbp=Decimal("60000"),
            fee_gbp=Decimal("0"),
        )
    ]

    outcome = match_disposals(acqs, disps)

    result = outcome.disposals[0]
    assert [m.rule for m in result.matches] == [MatchRule.SAME_DAY, MatchRule.SECTION_104]
    assert result.matches[0].cost_gbp == Decimal("30000")  # same-day, own cost
    assert result.matches[1].cost_gbp == Decimal("10000")  # 1 BTC from pool at 10000
    assert result.gain_gbp == Decimal("20000")  # 60000 − 40000 − 0

    # 1 BTC left in the pool at its averaged cost
    assert outcome.pools["BTC"].quantity == Decimal("1")
    assert outcome.pools["BTC"].cost_gbp == Decimal("10000")


def test_thirty_day_reacquisition_matches_at_own_cost() -> None:
    """A sell followed by a re-buy within 30 days (bed & breakfast): the disposal
    matches the later acquisition at its own cost, leaving the pool untouched."""
    acqs = [
        Acquisition(
            date=date(2023, 1, 1),
            asset="BTC",
            quantity=Decimal("1"),
            cost_gbp=Decimal("10000"),  # pre-existing pool, must stay untouched
        ),
        Acquisition(
            date=date(2024, 1, 20),
            asset="BTC",
            quantity=Decimal("1"),
            cost_gbp=Decimal("25000"),  # re-buy, 10 days after the disposal
        ),
    ]
    disps = [
        Disposal(
            date=date(2024, 1, 10),
            asset="BTC",
            quantity=Decimal("1"),
            proceeds_gbp=Decimal("30000"),
            fee_gbp=Decimal("0"),
        )
    ]

    outcome = match_disposals(acqs, disps)

    result = outcome.disposals[0]
    assert [m.rule for m in result.matches] == [MatchRule.THIRTY_DAY]
    assert result.matches[0].cost_gbp == Decimal("25000")  # own cost, not pool's 10000
    assert result.gain_gbp == Decimal("5000")  # 30000 − 25000 − 0

    # the original holding is undisturbed
    assert outcome.pools["BTC"].quantity == Decimal("1")
    assert outcome.pools["BTC"].cost_gbp == Decimal("10000")


def test_thirty_day_partial_then_spills_to_s104() -> None:
    """A disposal larger than the 30-day re-buy matches the re-buy at own cost,
    then draws the remainder from the pool — reported in priority order."""
    acqs = [
        Acquisition(
            date=date(2023, 1, 1),
            asset="BTC",
            quantity=Decimal("2"),
            cost_gbp=Decimal("20000"),  # pool: 10000 per BTC
        ),
        Acquisition(
            date=date(2024, 1, 15),
            asset="BTC",
            quantity=Decimal("1"),
            cost_gbp=Decimal("15000"),  # re-buy, 5 days after the disposal
        ),
    ]
    disps = [
        Disposal(
            date=date(2024, 1, 10),
            asset="BTC",
            quantity=Decimal("2"),
            proceeds_gbp=Decimal("50000"),
            fee_gbp=Decimal("0"),
        )
    ]

    outcome = match_disposals(acqs, disps)

    result = outcome.disposals[0]
    assert [m.rule for m in result.matches] == [MatchRule.THIRTY_DAY, MatchRule.SECTION_104]
    assert result.matches[0].cost_gbp == Decimal("15000")  # 30-day, own cost
    assert result.matches[1].cost_gbp == Decimal("10000")  # 1 BTC from pool
    assert result.gain_gbp == Decimal("25000")  # 50000 − 25000 − 0

    assert outcome.pools["BTC"].quantity == Decimal("1")
    assert outcome.pools["BTC"].cost_gbp == Decimal("10000")


def test_thirty_day_window_includes_day_thirty() -> None:
    """An acquisition exactly 30 days after the disposal is still bed & breakfast."""
    acqs = [
        Acquisition(
            date=date(2024, 1, 31),  # disposal + 30 days
            asset="BTC",
            quantity=Decimal("1"),
            cost_gbp=Decimal("25000"),
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

    result = outcome.disposals[0]
    assert [m.rule for m in result.matches] == [MatchRule.THIRTY_DAY]
    assert result.matches[0].cost_gbp == Decimal("25000")
    assert outcome.pools["BTC"].quantity == Decimal("0")


def test_thirty_day_window_excludes_day_thirty_one() -> None:
    """An acquisition 31 days after the disposal is out of window: the disposal
    falls through to the pool and the late re-buy just carries forward."""
    acqs = [
        Acquisition(
            date=date(2023, 1, 1),
            asset="BTC",
            quantity=Decimal("1"),
            cost_gbp=Decimal("10000"),  # pool
        ),
        Acquisition(
            date=date(2024, 2, 1),  # disposal + 31 days, out of window
            asset="BTC",
            quantity=Decimal("1"),
            cost_gbp=Decimal("25000"),
        ),
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

    result = outcome.disposals[0]
    assert [m.rule for m in result.matches] == [MatchRule.SECTION_104]
    assert result.matches[0].cost_gbp == Decimal("10000")  # from the pool, not the late buy
    assert result.gain_gbp == Decimal("20000")  # 30000 − 10000 − 0

    # the out-of-window buy just carries forward in the pool
    assert outcome.pools["BTC"].quantity == Decimal("1")
    assert outcome.pools["BTC"].cost_gbp == Decimal("25000")


def test_disposal_exceeding_pool_matches_available_then_flags_short() -> None:
    """A disposal larger than all known stock draws the pool at real cost, then the
    true excess becomes a nil-cost SECTION_104_SHORT chunk with a flag — the signal
    that acquisition history is incomplete."""
    acqs = [
        Acquisition(
            date=date(2023, 1, 1),
            asset="BTC",
            quantity=Decimal("1"),
            cost_gbp=Decimal("10000"),  # only 1 BTC of known stock
        )
    ]
    disps = [
        Disposal(
            date=date(2024, 1, 1),
            asset="BTC",
            quantity=Decimal("2"),  # 1 BTC more than the pool can supply
            proceeds_gbp=Decimal("60000"),
            fee_gbp=Decimal("0"),
        )
    ]

    outcome = match_disposals(acqs, disps)

    result = outcome.disposals[0]
    assert [m.rule for m in result.matches] == [
        MatchRule.SECTION_104,
        MatchRule.SECTION_104_SHORT,
    ]
    assert result.matches[0].quantity == Decimal("1")
    assert result.matches[0].cost_gbp == Decimal("10000")  # pool part at real cost
    assert result.matches[1].quantity == Decimal("1")
    assert result.matches[1].cost_gbp == Decimal("0")  # unknown chunk: nil cost
    assert result.allowable_cost_gbp == Decimal("10000")
    assert result.gain_gbp == Decimal("50000")  # 60000 − 10000 − 0

    # pool emptied, nothing to carry forward
    assert outcome.pools["BTC"].quantity == Decimal("0")
    assert outcome.pools["BTC"].cost_gbp == Decimal("0")

    # one short flag naming the affected asset
    assert len(outcome.flags) == 1
    assert outcome.flags[0].code == "SECTION_104_SHORT"
    assert outcome.flags[0].asset == "BTC"


def test_disposal_with_no_pool_is_entirely_short_at_nil_cost() -> None:
    """A disposal with no matching acquisitions at all is one SECTION_104_SHORT
    chunk at nil cost: the whole proceeds (less fee) are gain, and a flag fires."""
    disps = [
        Disposal(
            date=date(2024, 1, 1),
            asset="BTC",
            quantity=Decimal("1"),
            proceeds_gbp=Decimal("30000"),
            fee_gbp=Decimal("100"),
        )
    ]

    outcome = match_disposals([], disps)

    result = outcome.disposals[0]
    assert [m.rule for m in result.matches] == [MatchRule.SECTION_104_SHORT]
    assert result.matches[0].quantity == Decimal("1")
    assert result.matches[0].cost_gbp == Decimal("0")
    assert result.gain_gbp == Decimal("29900")  # 30000 − 0 − 100 fee

    assert outcome.pools["BTC"].quantity == Decimal("0")
    assert outcome.pools["BTC"].cost_gbp == Decimal("0")
    assert len(outcome.flags) == 1
    assert outcome.flags[0].code == "SECTION_104_SHORT"
    assert outcome.flags[0].asset == "BTC"


def test_single_disposal_draws_all_three_rules_in_priority_order() -> None:
    """One disposal spanning same-day, 30-day and s104: each rule contributes one
    BTC at its own cost, reported same-day → 30-day → s104."""
    acqs = [
        Acquisition(
            date=date(2023, 1, 1),
            asset="BTC",
            quantity=Decimal("3"),
            cost_gbp=Decimal("30000"),  # pool: 10000 per BTC
        ),
        Acquisition(
            date=date(2024, 6, 10),
            asset="BTC",
            quantity=Decimal("1"),
            cost_gbp=Decimal("25000"),  # same day as the disposal
        ),
        Acquisition(
            date=date(2024, 6, 20),
            asset="BTC",
            quantity=Decimal("1"),
            cost_gbp=Decimal("22000"),  # 10 days after the disposal
        ),
    ]
    disps = [
        Disposal(
            date=date(2024, 6, 10),
            asset="BTC",
            quantity=Decimal("3"),
            proceeds_gbp=Decimal("90000"),
            fee_gbp=Decimal("0"),
        )
    ]

    outcome = match_disposals(acqs, disps)

    result = outcome.disposals[0]
    assert [m.rule for m in result.matches] == [
        MatchRule.SAME_DAY,
        MatchRule.THIRTY_DAY,
        MatchRule.SECTION_104,
    ]
    assert result.matches[0].cost_gbp == Decimal("25000")  # same-day, own cost
    assert result.matches[1].cost_gbp == Decimal("22000")  # 30-day, own cost
    assert result.matches[2].cost_gbp == Decimal("10000")  # s104, pool average
    assert result.gain_gbp == Decimal("33000")  # 90000 − 57000 − 0

    # 2 BTC left in the pool at the averaged 10000
    assert outcome.pools["BTC"].quantity == Decimal("2")
    assert outcome.pools["BTC"].cost_gbp == Decimal("20000")


def test_same_day_beats_thirty_day_for_a_contested_acquisition() -> None:
    """An acquisition that is same-day for one disposal and within 30 days of an
    earlier disposal is claimed by the same-day disposal first; the earlier
    disposal falls to the pool."""
    acqs = [
        Acquisition(
            date=date(2023, 1, 1),
            asset="BTC",
            quantity=Decimal("2"),
            cost_gbp=Decimal("20000"),  # pool: 10000 per BTC
        ),
        Acquisition(
            date=date(2024, 1, 5),
            asset="BTC",
            quantity=Decimal("1"),
            cost_gbp=Decimal("20000"),  # same-day for B, within 30 days of A
        ),
    ]
    disps = [
        Disposal(
            date=date(2024, 1, 1),  # A — earlier
            asset="BTC",
            quantity=Decimal("1"),
            proceeds_gbp=Decimal("15000"),
            fee_gbp=Decimal("0"),
        ),
        Disposal(
            date=date(2024, 1, 5),  # B — same day as the contested acquisition
            asset="BTC",
            quantity=Decimal("1"),
            proceeds_gbp=Decimal("25000"),
            fee_gbp=Decimal("0"),
        ),
    ]

    outcome = match_disposals(acqs, disps)

    disposal_a = outcome.disposals[0]  # sorted by date: A first
    disposal_b = outcome.disposals[1]

    # B claims the 2024-01-05 acquisition under same-day
    assert [m.rule for m in disposal_b.matches] == [MatchRule.SAME_DAY]
    assert disposal_b.matches[0].cost_gbp == Decimal("20000")

    # A gets nothing from that acquisition under 30-day; it falls to the pool
    assert [m.rule for m in disposal_a.matches] == [MatchRule.SECTION_104]
    assert disposal_a.matches[0].cost_gbp == Decimal("10000")

    assert outcome.pools["BTC"].quantity == Decimal("1")
    assert outcome.pools["BTC"].cost_gbp == Decimal("10000")
