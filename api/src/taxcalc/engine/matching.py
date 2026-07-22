"""Section 104 disposal matching — PURE, zero I/O.

Valued events in (GBP already attached by the valuation stage), disposals out.
Batch semantics: the engine sorts internally, so input order never changes the
result. Decimal throughout — no floats, no epsilon fudging. Full precision is
kept here; rounding happens only at the reporting boundary.

Only the Section 104 pool path is implemented so far. Same-day, 30-day and
pool-short handling arrive with the tests that demand them.
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


def match_disposals(
    acquisitions: list[Acquisition],
    disposals: list[Disposal],
) -> MatchOutcome:
    """Match disposals to acquisitions per asset and return the full working."""
    assets = sorted({a.asset for a in acquisitions} | {d.asset for d in disposals})
    results: list[DisposalResult] = []
    pools: dict[str, PoolState] = {}

    for asset in assets:
        acqs = [a for a in acquisitions if a.asset == asset]
        disps = [d for d in disposals if d.asset == asset]

        # Chronological pass; on a same-date tie, acquisitions land before disposals.
        events: list[tuple[dt.date, int, Acquisition | Disposal]] = [
            (a.date, 0, a) for a in acqs
        ] + [(d.date, 1, d) for d in disps]
        events.sort(key=lambda e: (e[0], e[1]))

        pool_qty = _ZERO
        pool_cost = _ZERO
        for _, kind, obj in events:
            if kind == 0:
                assert isinstance(obj, Acquisition)
                pool_qty += obj.quantity
                pool_cost += obj.cost_gbp
            else:
                assert isinstance(obj, Disposal)
                cost = pool_cost * (obj.quantity / pool_qty)
                results.append(
                    DisposalResult(
                        disposal=obj,
                        matches=(Match(MatchRule.SECTION_104, obj.quantity, cost),),
                    )
                )
                pool_qty -= obj.quantity
                pool_cost -= cost

        pools[asset] = PoolState(asset=asset, quantity=pool_qty, cost_gbp=pool_cost)

    results.sort(key=lambda r: (r.disposal.date, r.disposal.asset))
    return MatchOutcome(disposals=tuple(results), pools=pools, flags=())
