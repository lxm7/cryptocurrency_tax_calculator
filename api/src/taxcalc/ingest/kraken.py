"""Kraken spot 'ledgers' CSV → classified, price-free ledger transactions.

A Kraken trade is two rows sharing one ``refid`` — a crypto leg and a fiat (or, for
crypto-to-crypto, a second crypto) leg. Rows are grouped by refid, the crypto
leg's sign classifies acquisition vs disposal, and the fiat counter-leg plus fees
are carried in NATIVE units for the valuation stage to price. No GBP, no prices, no
I/O beyond the text handed in.

Slice 1 handles the fiat-paired spot trade. Asset-symbol normalisation (XXBT→BTC,
``.S``/``.P`` staking suffixes, MATIC→POL rebrand), income and internal-move
classification, and pre-data opening-balance detection arrive in later slices.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

FIAT = frozenset({"GBP", "USD", "EUR"})


class TxnKind(Enum):
    ACQUISITION = "acquisition"
    DISPOSAL = "disposal"
    INCOME = "income"
    INTERNAL = "internal"


@dataclass(frozen=True)
class LedgerTxn:
    """One taxable crypto movement, classified, in native units (no GBP yet).

    ``fees`` are ``(asset, amount)`` legs in their own currency; ``counter`` is the
    paired fiat leg ``(asset, abs amount)`` when the trade has one, else ``None``
    (crypto-to-crypto / external deposit → valuation uses market value instead).
    """

    refid: str
    date: dt.date
    kind: TxnKind
    asset: str
    quantity: Decimal
    fees: tuple[tuple[str, Decimal], ...]
    counter: tuple[str, Decimal] | None


@dataclass(frozen=True)
class _Row:
    refid: str
    time: dt.datetime
    type: str
    subtype: str
    asset: str
    amount: Decimal
    fee: Decimal


def _normalise_asset(asset: str) -> str:
    # Slice 1: identity. XXBT→BTC, staking suffixes and rebrands land in a later
    # slice with their own tests.
    return asset


def _read_rows(text: str) -> list[_Row]:
    rows: list[_Row] = []
    for r in csv.DictReader(io.StringIO(text)):
        rows.append(
            _Row(
                refid=r["refid"],
                time=dt.datetime.fromisoformat(r["time"]),
                type=r["type"],
                subtype=(r.get("subtype") or ""),
                asset=_normalise_asset(r["asset"]),
                amount=Decimal(r["amount"]),
                fee=Decimal(r["fee"] or "0"),
            )
        )
    return rows


def parse(text: str) -> list[LedgerTxn]:
    """Kraken ledger CSV text → ledger transactions, oldest first."""
    groups: dict[str, list[_Row]] = {}
    for row in _read_rows(text):
        groups.setdefault(row.refid, []).append(row)

    txns: list[LedgerTxn] = []
    for refid, legs in groups.items():
        fees = tuple((leg.asset, leg.fee) for leg in legs if leg.fee > 0)
        fiat_legs = [leg for leg in legs if leg.asset in FIAT]
        counter: tuple[str, Decimal] | None = None
        if fiat_legs:
            counter = (fiat_legs[0].asset, abs(fiat_legs[0].amount))
        # One taxable txn per crypto leg. A fiat-paired trade has exactly one; a
        # crypto-to-crypto trade (two crypto legs, no fiat) yields a disposal and an
        # acquisition — its fee attribution is a later slice's concern.
        for leg in legs:
            if leg.asset in FIAT:
                continue
            kind = TxnKind.ACQUISITION if leg.amount > 0 else TxnKind.DISPOSAL
            txns.append(
                LedgerTxn(
                    refid=refid,
                    date=leg.time.date(),
                    kind=kind,
                    asset=leg.asset,
                    quantity=abs(leg.amount),
                    fees=fees,
                    counter=counter,
                )
            )

    txns.sort(key=lambda t: (t.date, t.kind.value))
    return txns
