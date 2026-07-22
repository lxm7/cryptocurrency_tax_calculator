"""Section 104 disposal matching — PURE, zero I/O.

Valued events in (GBP already attached by the valuation stage), disposals out.
Batch semantics: the engine sorts internally, so input order never changes the
result. Decimal throughout — no floats, no epsilon fudging. Full precision is
kept here; rounding happens only at the reporting boundary.

The full HMRC priority pipeline is implemented: same-day → 30-day (bed-and-
breakfast) → Section 104 pool, with a nil-cost SECTION_104_SHORT fallback and a
flag when a disposal exceeds all known stock (incomplete acquisition history).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

_ZERO = Decimal("0")


class MatchRule(Enum):
    """HMRC share-identification rules, in priority order."""

    SAME_DAY = "same-day"
    THIRTY_DAY = "30-day"
    SECTION_104 = "s104"
    SECTION_104_SHORT = "s104-short"  # disposal exceeds known pool (incomplete history)


@dataclass(frozen=True)
class Acquisition:
    date: dt.date
    asset: str
    quantity: Decimal
    cost_gbp: Decimal  # consideration incl. incidental acquisition costs (fees)


@dataclass(frozen=True)
class Disposal:
    date: dt.date
    asset: str
    quantity: Decimal
    proceeds_gbp: Decimal
    fee_gbp: Decimal  # incidental disposal costs, deducted from the gain


@dataclass(frozen=True)
class Match:
    """One chunk of a disposal matched to a cost under a given rule."""

    rule: MatchRule
    quantity: Decimal
    cost_gbp: Decimal


@dataclass(frozen=True)
class DisposalResult:
    disposal: Disposal
    matches: tuple[Match, ...]

    @property
    def allowable_cost_gbp(self) -> Decimal:
        total = _ZERO
        for m in self.matches:
            total += m.cost_gbp
        return total

    @property
    def gain_gbp(self) -> Decimal:
        return self.disposal.proceeds_gbp - self.allowable_cost_gbp - self.disposal.fee_gbp


@dataclass(frozen=True)
class PoolState:
    asset: str
    quantity: Decimal
    cost_gbp: Decimal


@dataclass(frozen=True)
class Flag:
    code: str
    asset: str
    message: str


@dataclass(frozen=True)
class MatchOutcome:
    disposals: tuple[DisposalResult, ...]
    pools: dict[str, PoolState]
    flags: tuple[Flag, ...]


_THIRTY_DAYS = dt.timedelta(days=30)


@dataclass
class _Lot:
    """Internal mutable working lot. HMRC treats all acquisitions on one day as a
    single acquisition, so same-date acquisitions are collapsed into one lot."""

    date: dt.date
    quantity: Decimal
    cost_gbp: Decimal


@dataclass
class _Work:
    """A disposal being worked through the priority pipeline: how much is still
    unmatched and the matches accumulated so far, in priority order."""

    disposal: Disposal
    remaining: Decimal
    matches: list[Match]


def _collapse_by_date(acqs: list[Acquisition]) -> list[_Lot]:
    """One lot per acquisition date, oldest first, costs summed (s105 pooling)."""
    by_date: dict[dt.date, _Lot] = {}
    for a in acqs:
        lot = by_date.get(a.date)
        if lot is None:
            by_date[a.date] = _Lot(a.date, a.quantity, a.cost_gbp)
        else:
            lot.quantity += a.quantity
            lot.cost_gbp += a.cost_gbp
    return [by_date[d] for d in sorted(by_date)]


def _take(lot: _Lot, quantity: Decimal) -> Decimal:
    """Consume `quantity` from a lot, returning its apportioned cost. The lot's
    remaining cost is reduced by subtraction so matched + remaining is conserved
    exactly even when the split does not terminate (e.g. thirds)."""
    cost = lot.cost_gbp * quantity / lot.quantity
    lot.quantity -= quantity
    lot.cost_gbp -= cost
    return cost


def _match_asset(
    acqs: list[Acquisition],
    disps: list[Disposal],
) -> tuple[list[DisposalResult], PoolState, list[Flag]]:
    """Match one asset's disposals through the priority pipeline, returning the
    per-disposal working and the pool carried forward.

    Three passes over shared mutable lots, in strict HMRC priority. Each pass only
    ever sees what earlier passes left, so the s104 pool is built from residual
    stock — no acquisition is ever poured and then clawed back out.
    """
    asset = acqs[0].asset if acqs else disps[0].asset
    lots = _collapse_by_date(acqs)  # one lot per date, oldest first
    works = [_Work(d, d.quantity, []) for d in sorted(disps, key=lambda d: d.date)]

    # Pass 1 — same-day (s105). Bind each disposal to the lot on its own day first,
    # globally, so a same-day disposal always outranks an earlier disposal's 30-day
    # claim on the same acquisition.
    lot_by_date = {lot.date: lot for lot in lots}
    for w in works:
        lot = lot_by_date.get(w.disposal.date)
        if lot is not None and w.remaining > _ZERO and lot.quantity > _ZERO:
            qty = min(w.remaining, lot.quantity)
            w.matches.append(Match(MatchRule.SAME_DAY, qty, _take(lot, qty)))
            w.remaining -= qty

    # Pass 2 — 30-day / bed-and-breakfast (s106A). Earliest disposal first; within
    # each, acquisitions in (date, date+30] FIFO, matched at their own cost.
    for w in works:
        if w.remaining <= _ZERO:
            continue
        window_end = w.disposal.date + _THIRTY_DAYS
        for lot in lots:  # oldest first → FIFO
            if w.remaining <= _ZERO:
                break
            if lot.quantity > _ZERO and w.disposal.date < lot.date <= window_end:
                qty = min(w.remaining, lot.quantity)
                w.matches.append(Match(MatchRule.THIRTY_DAY, qty, _take(lot, qty)))
                w.remaining -= qty

    # Pass 3 — Section 104. Pour residual lots chronologically; each disposal draws
    # its leftover from the pool as it stood on its date.
    pool = _Lot(dt.date.min, _ZERO, _ZERO)
    next_lot = 0  # lots[:next_lot] have been poured into the pool
    flags: list[Flag] = []
    for w in works:
        while next_lot < len(lots) and lots[next_lot].date < w.disposal.date:
            lot = lots[next_lot]
            pool.quantity += lot.quantity
            pool.cost_gbp += lot.cost_gbp
            next_lot += 1
        if w.remaining > _ZERO and pool.quantity > _ZERO:
            qty = min(w.remaining, pool.quantity)
            w.matches.append(Match(MatchRule.SECTION_104, qty, _take(pool, qty)))
            w.remaining -= qty
        if w.remaining > _ZERO:
            # Disposal exceeds all known stock — incomplete acquisition history. Any
            # pool part was matched above at real cost; the true excess has no cost
            # basis, so it becomes a nil-cost SECTION_104_SHORT chunk (its full
            # proceeds fall into the gain) and a flag warns the user to supply the
            # missing earlier acquisitions to reduce it.
            short_qty = w.remaining
            w.matches.append(Match(MatchRule.SECTION_104_SHORT, short_qty, _ZERO))
            w.remaining = _ZERO
            flags.append(
                Flag(
                    code=MatchRule.SECTION_104_SHORT.name,
                    asset=asset,
                    message=(
                        f"disposal on {w.disposal.date} of {short_qty} {asset} "
                        f"exceeds available pool — cost basis missing (incomplete history?)"
                    ),
                )
            )

    # Carry forward the pool plus any residual stock never drawn on (same-day and
    # 30-day leftovers, plus acquisitions after the last disposal).
    for lot in lots[next_lot:]:
        pool.quantity += lot.quantity
        pool.cost_gbp += lot.cost_gbp

    results = [DisposalResult(disposal=w.disposal, matches=tuple(w.matches)) for w in works]
    return results, PoolState(asset=asset, quantity=pool.quantity, cost_gbp=pool.cost_gbp), flags


def match_disposals(
    acquisitions: list[Acquisition],
    disposals: list[Disposal],
) -> MatchOutcome:
    """Match disposals to acquisitions per asset and return the full working."""
    assets = sorted({a.asset for a in acquisitions} | {d.asset for d in disposals})
    results: list[DisposalResult] = []
    pools: dict[str, PoolState] = {}
    flags: list[Flag] = []

    for asset in assets:
        acqs = [a for a in acquisitions if a.asset == asset]
        disps = [d for d in disposals if d.asset == asset]
        asset_results, pools[asset], asset_flags = _match_asset(acqs, disps)
        results.extend(asset_results)
        flags.extend(asset_flags)

    results.sort(key=lambda r: (r.disposal.date, r.disposal.asset))
    return MatchOutcome(disposals=tuple(results), pools=pools, flags=tuple(flags))
