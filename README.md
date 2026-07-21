# crypto-tax-calc

UK crypto **Capital Gains Tax calculation and reporting aid** — turns a Kraken
ledger export into per-tax-year gain/loss figures using HMRC share-matching
(same-day → 30-day → Section 104 pool), with an assistant that explains each
treatment against cited HMRC guidance.

> **Not tax advice.** A calculation and reporting aid with cited guidance.

**v1 scope (deliberate):** CGT on disposals only · Kraken only · staking/mining/
airdrops flagged as income, never computed. See `docs/0-master-12-week-build.md`.

## Status

Week 1 — foundations. Build order (reordered from the plan): price-source
verification → minimal Python harness → **engine (test-first)** → full-stack
scaffold → ingest/valuation.

## Price-history source (Week-1 decision — LOCKED 2026-07-21)

**Kraken Trades API + Frankfurter (ECB) FX — free, exchange-native**, behind a
`providers/` protocol so a paid aggregator can be swapped in later without
touching the engine. The ledger's own fiat leg gives cost/proceeds directly; the
price source is only a fallback for crypto→crypto legs, income, and external
deposits.

Verified live on 2026-07-21:

| Source | Historical reach | Key? | Cost |
| --- | --- | --- | --- |
| Kraken **Trades** (chosen) | full — to pair inception (BTC: 2014-11-06); `since` seeks directly to any date | no | **free** |
| Kraken OHLC | ~720-day hard wall (insufficient) | no | free |
| CoinGecko free | 365-day hard cap (all endpoints) | no | free |
| CoinGecko Analyst | 2013→ (cheapest full-history paid tier) | yes | $129/mo |
| CryptoCompare | now CoinDesk/CCData — `401 key required` | yes | — |
| Frankfurter (ECB FX) | 1999→ | no | free |

Rationale: Kraken-only v1 means Trades covers 100% of in-scope assets; venue
price is the most HMRC-defensible valuation; £0/mo preserves margin on a
£15–25/tax-year product. CoinGecko stays a future drop-in for multi-exchange.

## Layout

```
api/        FastAPI + Celery backend; src/taxcalc/engine is PURE (zero I/O)
docs/       build plan
reference/  crypto-to-gbp-tax.py — prototype oracle, not shipped code
```

## Dev quickstart

```bash
uv sync --project api                 # provisions Python 3.13, installs dev deps
uv run --project api pytest -q        # tests
uv run --project api ruff check api   # lint
uv run --project api mypy api/src     # types (strict)
```
