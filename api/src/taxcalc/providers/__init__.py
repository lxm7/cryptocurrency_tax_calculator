"""Price providers — adapters that satisfy the ``PricePort`` protocol.

The protocol lives here; the real Kraken-Trades + Frankfurter-FX adapter (async
I/O, snapshot cache) lands in a later slice and stays OUTSIDE the pure engine and
valuation stages. Tests inject a static fake.
"""
