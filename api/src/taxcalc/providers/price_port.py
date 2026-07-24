"""The price port — the seam between the pure valuation stage and any price source.

Valuation depends only on this ``Protocol``: given an asset and a date, return the
GBP value of one unit. Fiat is priced too (GBP → 1, USD/EUR → that day's FX), so
every leg — crypto or fiat — is valued through one uniform call.

The port is deliberately **synchronous**: the real adapter does its async HTTP I/O
ahead of time and resolves a cache (→ the ``price_snapshots`` table / the Celery
valuation job), so valuation reads already-resolved prices and stays zero-I/O and
deterministic, exactly like the matching engine.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Protocol


class PricePort(Protocol):
    def price_gbp(self, asset: str, on: dt.date) -> Decimal:
        """GBP value of one unit of ``asset`` on ``on`` (fiat included)."""
        ...
