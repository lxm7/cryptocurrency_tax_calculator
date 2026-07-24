"""Valuation stage — price-free ledger transactions → engine-ready acquisitions and
disposals, in GBP.

The ONE consumer of the ``PricePort``. Every GBP figure is resolved here: a fiat
counter-leg is valued at its own currency's rate (GBP → 1, USD/EUR → FX); a
crypto-to-crypto or externally-deposited leg with no fiat counterpart is valued at
the moved asset's market price; fees are converted from their native asset. No
rounding — full ``Decimal`` precision is carried to the reporting boundary. Pure
and deterministic: prices come from the injected port, which reads a cache resolved
ahead of time, never live I/O.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from taxcalc.engine.matching import Acquisition, Disposal, Flag
from taxcalc.ingest.kraken import FIAT, LedgerTxn, TxnKind
from taxcalc.providers.price_port import PricePort


@dataclass(frozen=True)
class Income:
    """A reward/airdrop: taxed as misc income at receipt AND entering the s104 pool
    at the same gross GBP value (the acquisition side is emitted separately)."""

    date: dt.date
    asset: str
    quantity: Decimal
    gross_gbp: Decimal


@dataclass(frozen=True)
class ValuationResult:
    acquisitions: tuple[Acquisition, ...]
    disposals: tuple[Disposal, ...]
    income: tuple[Income, ...] = ()
    flags: tuple[Flag, ...] = ()


def _fees_gbp(txn: LedgerTxn, price: PricePort) -> Decimal:
    total = Decimal("0")
    for asset, amount in txn.fees:
        total += amount * price.price_gbp(asset, txn.date)
    return total


def _consideration_gbp(txn: LedgerTxn, price: PricePort) -> Decimal:
    """The other side of the trade in GBP: the fiat paid/received when a fiat leg
    exists, else the market value of the crypto moved (crypto-to-crypto or an
    external deposit)."""
    if txn.counter is not None and txn.counter[0] in FIAT:
        asset, amount = txn.counter
        return amount * price.price_gbp(asset, txn.date)
    return txn.quantity * price.price_gbp(txn.asset, txn.date)


def value(txns: list[LedgerTxn], price: PricePort) -> ValuationResult:
    """Attach GBP to each ledger transaction and emit engine inputs."""
    acquisitions: list[Acquisition] = []
    disposals: list[Disposal] = []
    for txn in txns:
        if txn.kind is TxnKind.ACQUISITION:
            cost = _consideration_gbp(txn, price) + _fees_gbp(txn, price)
            acquisitions.append(Acquisition(txn.date, txn.asset, txn.quantity, cost))
        elif txn.kind is TxnKind.DISPOSAL:
            proceeds = _consideration_gbp(txn, price)
            disposals.append(
                Disposal(txn.date, txn.asset, txn.quantity, proceeds, _fees_gbp(txn, price))
            )
        # INCOME / INTERNAL handled in later slices
    return ValuationResult(tuple(acquisitions), tuple(disposals))
