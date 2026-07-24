"""Ingest + valuation pipeline — behaviour tests (vertical TDD slices).

Slice 1: a Kraken 'ledgers' CSV with one fiat→crypto buy and one crypto→fiat sell
of the same asset flows through ingest → valuation → matching to the right gain.
Fiat legs only, so the price port is exercised trivially (GBP → 1); crypto-to-
crypto, FX, income and asset normalisation arrive in later slices.
"""

from datetime import date
from decimal import Decimal

from taxcalc.engine.matching import match_disposals
from taxcalc.ingest.kraken import TxnKind, parse
from taxcalc.providers.price_port import PricePort
from taxcalc.valuation.valuation import value

# buy 0.5 BTC for £10,000 (£10 fee) on 2025-05-01; sell 0.5 BTC for £15,000
# (£15 fee) on 2025-06-01. Each trade is two refid-paired rows: a crypto leg and
# a GBP leg. Fees sit on the GBP leg here.
LEDGER = """txid,refid,time,type,subtype,aclass,asset,amount,fee,balance
L1,R1,2025-05-01 10:00:00,trade,,currency,GBP,-10000.0,10.0,50000.0
L2,R1,2025-05-01 10:00:00,trade,,currency,BTC,0.5,0.0,0.5
L3,R2,2025-06-01 12:00:00,trade,,currency,BTC,-0.5,0.0,0.0
L4,R2,2025-06-01 12:00:00,trade,,currency,GBP,15000.0,15.0,65000.0
"""


class _GbpOnly:
    """Fake PricePort: GBP is 1:1; this slice needs no crypto or FX prices."""

    def price_gbp(self, asset: str, on: date) -> Decimal:
        if asset == "GBP":
            return Decimal("1")
        raise KeyError(f"no price for {asset} on {on}")


def _is_price_port(p: PricePort) -> PricePort:  # structural-typing check at import time
    return p


def test_buy_then_sell_via_fiat_legs_computes_gain() -> None:
    txns = parse(LEDGER)

    # ingest groups each refid and classifies the crypto leg by sign
    assert [(t.kind, t.asset, t.quantity) for t in txns] == [
        (TxnKind.ACQUISITION, "BTC", Decimal("0.5")),
        (TxnKind.DISPOSAL, "BTC", Decimal("0.5")),
    ]

    result = value(txns, _is_price_port(_GbpOnly()))

    assert len(result.acquisitions) == 1
    assert len(result.disposals) == 1
    assert result.acquisitions[0].cost_gbp == Decimal("10010")  # 10000 consideration + 10 fee
    assert result.disposals[0].proceeds_gbp == Decimal("15000")
    assert result.disposals[0].fee_gbp == Decimal("15")

    outcome = match_disposals(list(result.acquisitions), list(result.disposals))

    assert len(outcome.disposals) == 1
    assert outcome.disposals[0].gain_gbp == Decimal("4975")  # 15000 − 10010 − 15
    assert outcome.flags == ()
