# crypto-tax-calc — build context & handoff

_Last updated 2026-07-24. Read this first to continue the build in a new session._

## What this is

UK crypto **Capital Gains Tax calculation and reporting aid**: a Kraken ledger
CSV in → per-tax-year gain/loss via HMRC share-matching (same-day → 30-day →
Section 104 pool), plus an assistant that explains each treatment against cited
HMRC guidance. **Not tax advice.**

**v1 scope (deliberate):** CGT on disposals only · Kraken only · staking/mining/
airdrops flagged as income, never computed. Full 12-week plan:
`docs/0-master-12-week-build.md`.

## Where we are (build status)

Working the plan in a **reordered** sequence (engine before the full-stack
scaffold, because the engine is pure/highest-risk and needs no infra):

1. ✅ **Price-source verification** — locked Kraken Trades + Frankfurter FX (free).
2. ✅ **Minimal Python harness** — `api/` uv package, Python 3.13.11, pytest+ruff+mypy(strict) green.
3. 🔨 **Engine, test-first** ← *matching stage complete*. Full HMRC pipeline, exact (Fraction) + order-independent, property-tested (⑨/9 slices, 21 tests). Next: swap golden values → HMRC YAML fixtures.
4. ✅ **Full-stack scaffold** — docker-compose, Next.js `/chat`→FastAPI→Claude, Postgres schema (`users` + `price_snapshots` only), Flask health, Kamal + GitHub Actions CI. Merged (PR #3, `deploy-architecture`).
5. 🔨 **Ingest/valuation** ← *starting*. Kraken ledger parser → pure valuation stage wiring the price source (`PricePort`) into the matching engine. Last pure-logic gap before the tool computes on real input.

**Step 3 progress — TDD slices for `taxcalc.engine.matching`:**
- ✅ ① s104 single buy → full sell *(tracer, green)*
- ✅ ② partial disposal + carryforward *(green; + conservation test on indivisible split)*
- ✅ ③ multi-buy averaged pool *(green)*
- ✅ ④ same-day rule *(green; priority pipeline: same-day → [30-day slot] → s104)*
- ✅ ⑤ 30-day (bed & breakfast) *(green; approach A — three passes over residual lots, no clawback; window D+1…D+30 incl., FIFO, contested same-day-beats-30-day locked)*
- ✅ ⑥ priority interaction *(green; one disposal drawing all three rules in priority order)*
- ✅ ⑦ disposal-exceeds-pool → `SECTION_104_SHORT` *(green; **split**: pool part matched at real cost, true excess is a **nil-cost** short chunk; per-disposal `Flag`; covers the no-pool-at-all case)*
- ✅ ⑧ multi-asset isolation *(green; regression-lock — passed with no impl change, partitioning already correct: independent pools/costs, same-day across assets doesn't cross-match, short flags per-asset)*
- ✅ ⑨ determinism + conservation property tests *(Hypothesis, green; `tests/test_matching_properties.py`, `hypothesis` dev dep). Found + drove fixes for two real defects — see below.*
- ⬜ then swap golden slices onto **YAML fixtures + a real HMRC worked example** ← **NEXT**

**Immediate next action:** move off hand-picked golden values onto **declarative YAML
fixtures transcribed from real HMRC worked examples** (Cryptoassets Manual CRYPTO22200
pooling; CG share-identification CG51550+), loaded by a Pydantic loader (strings→Decimal,
reject bare floats). This is the transition out of pure-logic slices — the engine is
feature-complete for v1 matching; fixtures replace our own numbers with HMRC's oracle.

**⑨ earned its keep immediately — Hypothesis found two defects 18 example tests missed:**
1. **Cost apportionment wasn't exactly conservative** — Decimal division of non-terminating
   splits (e.g. £0.02 across sixths) drifted ~1e-28. **Fixed:** money + quantity are now
   carried internally as exact **`Fraction`**; `Match`/`PoolState` cost+qty and
   `gain_gbp`/`allowable_cost_gbp` are `Fraction` (exact). No rounding in the engine —
   pennies are the reporting boundary's job. Chosen over an epsilon-tolerance test to honour
   the project's "no epsilon fudging" stance.
2. **Same-date disposals were order-dependent** (scarce same-day stock + order-sensitive
   pool-draw). **Fixed:** disposals of one asset on one date are **aggregated into a synthetic
   `_Combined`**, matched once through all three passes, then each match is **split back to
   members pro-rata by quantity** — identical per-unit treatment, order-free, HMRC-consistent.

**⑦ resolved (conferred):** nil-cost + loud flag; split not lump; short is a
`SECTION_104_SHORT` `Match` in `matches[]`. Pool floors at zero; flag is per-disposal
(now per aggregated disposal-date). ④–⑨ done — full same-day → 30-day → s104 → short
pipeline in `_match_asset`, asset-isolated, exact, order-independent.

## Locked decisions (detail in `~/.claude/.../memory/`)

| Decision | Answer | Memory slug |
|---|---|---|
| Price source | Kraken Trades + Frankfurter FX, free, behind a `providers/` protocol | `price-source-decision` |
| Engine boundary | **C — two pure stages**: `valuation` (injected `PricePort`) → `matching` | — |
| Engine discipline | pure, zero-I/O, test-first, `Decimal` not float; reference is oracle not code | `section-104-engine-no-mcp` |
| Python | pinned **3.13** (`api/.python-version`; `uv sync --python 3.13` — `requires-python` alone let 3.14 slip in) | — |
| Deploy | VPS + docker-compose + **Kamal** + GitHub Actions CI (not K8s/EKS) | `deploy-architecture` |
| Fixtures | declarative **YAML** golden files (Pydantic loader: strings→Decimal, reject bare floats) **+** Python property tests | — |
| Data model | **ephemeral-free** (free tier): only `users` + `price_snapshots` in Postgres; per-user tax data held in Redis w/ TTL, never persisted; paid tier adds encrypted persistence later. Committed in `db/models.py`. | `deploy-architecture` |

## Open decisions (resolve before they block)

- **Pricing sub-decisions** (settle when building `pricing/`; affect fixture
  expected-values only): valuation methodology (leaning **daily close** vs
  price-at-timestamp); mechanism (leaning **Trades-uniform** vs OHLC≤720d + Trades beyond).
- **HMRC fixture refs**: pull real worked examples (Cryptoassets Manual CRYPTO22200
  pooling area; CG share-identification CG51550+) to transcribe verbatim as YAML fixtures.

## Conventions

- **No floats, no epsilon fudging.** Inputs are `Decimal`; the matching engine carries
  money + quantity as exact **`Fraction`** internally and in its matched output, because
  cost apportionment (÷ quantity) is the one lossy op — exact rationals make conservation
  exact. Full precision kept in the engine; **round to pennies only at the reporting boundary.**
- Engine is **pure / zero-I/O**. Two composed pure stages: `valuation` takes raw
  events + an injected `PricePort` protocol `(asset, date) → Decimal` (real
  Kraken adapter lives *outside* `engine/`, a static fake in tests) and applies
  the tax valuation rules (fiat-leg proceeds, crypto→crypto at market, fee
  allocation); `matching` takes valued events → disposals + pool + working.
- **Batch, not incremental** — the 30-day rule looks *forward*, so a disposal
  can't be finalised until later acquisitions are known. Recompute per asset.
- **Rich audit-trail output** — per disposal the list of `(rule, qty, cost)`
  matches, not just a net gain (needed for the explainer assistant + week-8
  reconciliation).
- **Fixtures**: golden worked-examples as YAML (Pydantic loader, strings→Decimal,
  reject bare floats — YAML parses `0.1` as a float, which would reintroduce the
  precision bug); invariants (determinism, pool conservation) as Python property
  tests. **Never snapshot expected values from the code** — they come from HMRC /
  hand-calculation. The reference `compute_cgt` may *propose* values, human-verified before freezing.
- **The model never does arithmetic**; **the agent is read-only, permanently**;
  **providers sit behind protocols** so sources swap without touching the engine.
- TDD: vertical slices, one test → one impl, no speculative infra.

## Repo layout & how to run

```
crypto-tax-calc/
├── CONTEXT.md                 ← this file
├── README.md                  ← price-source decision + verified limits
├── docs/0-master-12-week-build.md
├── reference/crypto-to-gbp-tax.py   ← prototype ORACLE (float; do not copy — Decimal in the real engine)
└── api/
    ├── pyproject.toml         ← uv pkg, ruff + mypy(strict) + pytest + hypothesis (dev)
    ├── .python-version        ← 3.13
    ├── src/taxcalc/
    │   ├── __init__.py
    │   ├── py.typed
    │   └── engine/
    │       ├── __init__.py
    │       └── matching.py    ← full HMRC pipeline, exact (Fraction), order-independent
    └── tests/
        ├── test_harness.py
        ├── test_matching.py             ← 18 example-based slices ①–⑧
        ├── test_matching_properties.py  ← ⑨ Hypothesis: determinism + cost/qty conservation
        └── fixtures/          ← empty; HMRC YAML golden files land next
```

```bash
uv sync --project api --python 3.13     # provisions 3.13, installs dev deps
uv run --project api pytest -q
uv run --project api ruff check api
uv run --project api mypy api/src
```

## Engine interface (current)

```python
# taxcalc.engine.matching   (inputs Decimal; internal + matched values exact Fraction)
Acquisition(date, asset, quantity: Decimal, cost_gbp: Decimal)   # cost incl. acq fee
Disposal(date, asset, quantity: Decimal, proceeds_gbp: Decimal, fee_gbp: Decimal)
MatchRule.{SAME_DAY, THIRTY_DAY, SECTION_104, SECTION_104_SHORT}
Match(rule, quantity: Fraction, cost_gbp: Fraction)             # exact; report rounds
DisposalResult(disposal, matches)  # .allowable_cost_gbp, .gain_gbp: Fraction (derived)
PoolState(asset, quantity: Fraction, cost_gbp: Fraction)
Flag(code, asset, message)
MatchOutcome(disposals, pools, flags)
match_disposals(acquisitions, disposals) -> MatchOutcome   # PURE, sorts + aggregates internally
```
Note `Fraction == Decimal` and `Fraction + Fraction == Decimal` are true in Python, so
example tests still assert against `Decimal("…")` literals unchanged.
Full HMRC priority pipeline in `_match_asset` as **three passes over shared residual
lots** (pass 1 same-day, pass 2 30-day/bed-and-breakfast in (D, D+30] FIFO at own
cost, pass 3 pour residual lots → s104 average, then a **nil-cost `SECTION_104_SHORT`**
fallback for any remainder that exceeds all known stock). No clawback: the pool is
built from what passes 1–2 leave. Same-date acqs collapsed to one lot (s105); cost
apportioned by subtraction so matched + carryforward conserve exactly. `_match_asset`
now also returns per-disposal short `Flag`s, collected in `match_disposals`.
**Tax-year summary (AEA, thresholds) is deliberately NOT in matching** —
that's a separate pure `reporting` module so annually-changing rates stay out of
the timeless core.

## Domain glossary

- **Disposal** — a taxable sale/swap of crypto (crypto→fiat or crypto→crypto).
- **Acquisition** — a buy or inbound event that builds cost basis.
- **Section 104 pool** — running average-cost pool of an asset; the default match.
- **Same-day rule** — acquisitions on the disposal's own day match first.
- **30-day / bed-and-breakfast** — acquisitions in the 30 days *after* a disposal match next.
- **Match** — one chunk of a disposal tied to a cost under one rule.
- **Carryforward** — pool qty/cost remaining after the period (`PoolState`).
- **Flag** — a non-fatal warning (e.g. disposal exceeds known pool = incomplete history).

## Working cadence (how the collaborator wants to work)

Senior peer, not an assistant. **Plan first, confer at a granular per-decision
level, present alternatives with trade-offs, push back on flawed choices.** This
is both a **learning exercise** and intended for **commercial release** — so the
"why" of each decision matters as much as the code.
