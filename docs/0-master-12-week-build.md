# Master 12-week build — UK crypto tax tool (tracker platform beneath)

_Supersedes all four prior docs (`ai-engineer-8-week-plan.md`, `0-flagship-repo-8-week-overlay.md`, `0-skills-gap-8-week-overlay.md`, `0-detailed-8-week-build.md`). One doc, one repo, three interview stories: full-stack, AI engineer, product engineer. The public product is the HMRC crypto tax tool; the portfolio tracker is the platform beneath it._

**Stack (carried forward):** Next.js + Vercel AI SDK · FastAPI (AI + API backend) · Flask (Stripe webhook slice) · Neon Postgres + pgvector · Celery + Redis · OpenAI `text-embedding-3-large` · Cohere `rerank-3.5` · Claude (prompt caching on) · RAGAS + Langfuse · PostHog · Docker from day 1 · Raw SDK + Pydantic AI or LangGraph for the agent loop (no LangChain).

**Head start:** `kraken_gbp_convert.py` seeds the valuation logic — but see week 2: the calc engine is a bigger job than "extend the script."

## Recent latest updates regarding tooling / best practices:

Skip Turborepo. It's a JS/TS task orchestrator — its caching and task graph only understand JS packages, so with a Python backend you'd get a monorepo tool managing exactly one app (web) and ignoring the half where the actual work lives. It earns its place in the RFP plan because that plan was all-TypeScript (Mastra, Drizzle, packages/ai). None of that transfers.

You want a plain polyglot monorepo: directories, one docker-compose.yml, per-language tooling. No orchestrator.

crypto-tax/
├── web/ # Next.js App Router, Vercel AI SDK
├── api/
│ ├── src/taxcalc/
│ │ ├── engine/ # s104 matching — PURE, zero I/O
│ │ ├── pricing/ # ported from kraken_gbp_convert.py
│ │ ├── ingest/ # kraken ledger parser
│ │ ├── rag/ agent/
│ │ ├── web/ # FastAPI routes
│ │ └── tasks/ # Celery (same package, different entrypoint)
│ ├── tests/fixtures/ # the worked examples, committed
│ └── pyproject.toml # uv + ruff + pytest
├── webhooks/ # Flask, Stripe only, ~100 lines
├── infra/ # Terraform
├── docker-compose.yml
└── .github/workflows/

Does the existing .py decide it? It decides the language split, not the repo tooling — and it should not decide the architecture. Your week-2 note is right that this isn't "extend the script." Treat kraken_gbp_convert.py as a reference implementation you port from, not a seed you grow around. Two specific pieces survive: the CoinGecko/Frankfurter fetch logic goes into pricing/ behind a provider interface, and its local cache becomes the price_snapshots table. The provider interface matters because your week-1 price-source decision is still open — if verification pushes you off CoinGecko, that should be a one-file change that never touches the engine.

The one structural decision that actually matters is unrelated to repo layout: engine/ must be a pure library. Transactions in, disposals out, no database session, no HTTP, no clock. That gets you three things the plan depends on — a fixture suite that runs in milliseconds so the CI gate stays fast, a determinism check that's trivial to write, and week 8's reconciliation step, where the agent's numeric claims are checked against the same pure function rather than a reimplementation. If the engine reaches into the DB, all three get harder and the last one gets genuinely painful.

On boilerplate: don't. The obvious candidate, tiangolo/full-stack-fastapi-template, ships SQLModel and a Vite/React frontend — you'd spend the first week deleting things and fighting choices you've already made differently. Your stack is specific enough that a template is a net cost. uv init on one side, create-next-app on the other, and you're scaffolded in an afternoon.

Two smaller calls while you're here: SQLAlchemy 2.0 with Alembic rather than SQLModel (Alembic autogenerate against SQLModel gets fiddly, and you flagged schema churn in week 2). And run the Celery worker as a separate container off the same image as the API — same code, different command — so you're not maintaining two dependency sets.

what are the best practices for scaffolding a full stack with python aia profcut in 2026

Synthesized modern Python stack patterns and architectural best practices
Synthesized modern Python stack patterns and architectural best practices

Three things have shifted since your plan was written that change the scaffolding advice specifically.

Toolchain: settled, no decisions needed

uv has become the default — it replaces pip, venv, virtualenv, pip-tools, pyenv and Poetry in one binary, with lockfiles and workspace support; Ruff replaces black, flake8, isort and a dozen others. Set tool.uv.package = true so uv treats the project as a real package rather than just a venv. mypy in strict mode on engine/ and pricing/ at minimum — the rest can be looser.
RepoForge.io Blog
Andrew Odendaal

Docker: multi-stage with uv sync --frozen --no-dev in the builder, copy the venv into a slim runtime. One image, two commands (uvicorn / celery worker).

The single highest-leverage scaffolding decision

Generate the TypeScript client from FastAPI's OpenAPI schema rather than hand-writing fetch calls. This is the one thing that makes a Python-backend/TS-frontend split feel as coherent as a TS monorepo, and it's what tRPC people are actually jealous of. Pydantic models become the source of truth; openapi-typescript + openapi-fetch gives you typed calls that break at compile time when a response shape changes.

Worth reading rather than adopting: vintasoftware/nextjs-fastapi-template, which does exactly this — typed clients generated from the OpenAPI schema, regenerated automatically when backend routes change, with uv for dependencies. Steal the codegen wiring; skip the rest, since it deploys the backend to Vercel and you need long-running Celery workers.
Vintasoft + 2

Layering, and the one rule that matters for you

The 2026 consensus structure is thin routers → services → repositories, with feature-based folders rather than type-based ones, plus a factory function for app creation and pydantic-settings for config. Standard, fine, adopt it.

But the rule that actually matters in your case is the one from last time: engine/ sits below the service layer and imports nothing from it. Not a repository, not a session, not a settings object. Everything else in this list is convention; that one is load-bearing for your CI eval gate and your week-8 reconciliation step.

Async: go async end-to-end on the API (SQLAlchemy 2.0 async + asyncpg, httpx.ASGITransport for tests). Note the seam — Celery tasks are sync, so your valuation jobs will want a sync engine alongside the async one. That's a known wart, not a mistake. If you'd rather avoid it, ARQ is async-native and Redis-backed, but Celery is the more recognised line on a CV.

Observability: instrument to OTel, not to a vendor

This is the real change since your plan was written. The field has converged on OpenTelemetry's GenAI semantic conventions as the vendor-neutral baseline — gen_ai.\* attributes standardising prompts, model names, token usage and tool calls — and the 2026 differentiator is whether a tool is OTel-native or needs a parallel proprietary instrumentation path. Langfuse's SDK emits standard OTel spans, so your existing choice is fine — but instrument through the OTel layer so traces are portable.
Firecrawl
Digital Applied Team

Two things to be aware of: ClickHouse acquired Langfuse in January 2026, with open-source licensing and self-hosting stated to remain unchanged, and most GenAI conventions were still experimental as of March 2026, so expect some churn. Being able to say "I instrumented to the OTel GenAI conventions so the backend is swappable" is a materially better interview answer than naming a SaaS.
Future AGI

Your week-7 framework decision got easier

Pydantic AI hit 1.0 in April 2026, stabilising the API and making it safe to build commercial products on. The split is now clean: Pydantic AI for mostly-linear agents that take input, call a few tools and return structured output; LangGraph for workflows that pause for human input, run parallel branches, or need durability and audit trails. The general recommendation is to start with Pydantic AI and graduate if the workflow shape demands it.
Insoftex + 2

Your three read-only tools answering one question is squarely the linear case, and the type-safety fit with a Pydantic-heavy codebase is real. The counterweight is the one I mentioned earlier: LangGraph gives you the LangChain-family keyword that job spec asks for. If the spec matters more than the build, that's a legitimate reason to pay the complexity cost — just make it a deliberate trade rather than a technical claim.

Directory-level additions to what I sketched before
api/
├── src/taxcalc/
│ ├── engine/ # pure, mypy --strict
│ ├── providers/ # price/FX/LLM adapters behind protocols
│ ├── prompts/ # versioned files, not inline strings
│ ├── obs/ # OTel setup, one place
│ └── ...
├── evals/ # golden set + runner, separate from tests/
└── tests/

Keeping evals/ out of tests/ matters more than it looks: unit tests must stay fast and deterministic for the CI gate to be trusted, and eval runs are neither. Same reason your plan hard-gates only the deterministic subset.

---

## Decisions already made (stop relitigating these)

| Decision                | Answer                                                                                                                              | Why                                                                                                                                        |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| RAG corpus              | HMRC Cryptoassets Manual (public HTML)                                                                                              | Real, messy, changes, high-stakes — better eval story than whitepapers. Also answers the old "will docs need Docling" question: no.        |
| v1 tax scope            | **CGT on disposals only.** Staking/mining/airdrops = flagged "income — out of scope", never computed                                | Kill decision #1. Income tax treatment is a different engine; flagging is honest and shippable.                                            |
| Exchanges at launch     | **Kraken only.** Upload attempts for other formats get logged + a "coming soon" capture                                             | Kill decision #2. Let failed uploads tell you which exchange is second.                                                                    |
| Agent write access      | **Read-only, permanently**                                                                                                          | Kill decision #3. An agent that can mutate tax records is a liability; explaining why is better interview material than any write feature. |
| Canonical demo question | "How does the 30-day rule apply to these three disposals?" — triggers ledger-query tool + calc tool + guidance retrieval in one run | Replaces the old L1-exposure question.                                                                                                     |
| Positioning, everywhere | "Calculation and reporting aid" with cited guidance. Never "tax advice".                                                            | Legal floor + the guardrails story.                                                                                                        |

---

## Phase 1 — Correctness core (weeks 1–3)

### Week 1 — Environment, skeleton, Docker, and the price-data decision

**Components:**

- [ ] Accounts + keys: Anthropic, OpenAI, Cohere, Neon (`CREATE EXTENSION vector;`), Langfuse, PostHog, Railway/Render, Vercel, GitHub
- [ ] Timeboxed reading (~4 hrs): Anthropic "Building Effective Agents" + Claude tool-use/prompt-caching docs
- [ ] Scaffold: Next.js shell → FastAPI `/chat` → Claude → UI, live at a URL
- [ ] Postgres schema v0: `transactions`, `disposals`, `pools`, `price_snapshots`, `users` (multi-user from day 1 — this is a product now)
- [ ] Bare Flask app, one health-check route
- [ ] Docker: Dockerfiles + `docker-compose.yml` (api, flask, postgres, redis)
- [ ] **Price-history source decision (new, blocking):** verify current limits, then commit. Candidates: CoinGecko paid tier, CryptoCompare free daily history, Kraken OHLC/trades. A 2024–25 filer needs GBP valuations at arbitrary past dates; free-tier CoinGecko's ~365-day window will not cover it. Budget for a small monthly cost if that's what verification says.

**Schema notes (refine, don't gold-plate):**

- `transactions` — id, user_id, asset, type (buy/sell/deposit/withdrawal/fee/flagged_income), quantity, price_gbp, fee_gbp, ts, source, external_id
- `pools` — Section 104 pool state per user+asset: quantity, allowable_cost_gbp, updated_at
- `disposals` — computed rows: matched rule (same-day / 30-day / s104), proceeds, cost, gain_loss_gbp, tax_year

**Done-when:** chat live at a URL · `docker compose up` brings the stack up · schema created · price source chosen with verified limits written in the README.

**Planning questions:**

1. Monorepo or split repos? (Recommend monorepo for one-link recruiter legibility.)
2. Alembic from day 1, or raw SQL until the schema settles? (Recommend Alembic now — schema will churn in week 2 and migrations are part of the full-stack story.)
3. Which price source did verification pick, and what's the monthly cost line?

---

### Week 2 — The tax calculation engine (the product's spine)

**What you're building.** The deterministic engine everything sits on. This is not "extend the Kraken script" — it's HMRC share-matching applied to crypto: **same-day rule → 30-day bed-and-breakfast rule → Section 104 pool**, in that order, per asset, with fees in allowable cost and crypto-to-crypto trades treated as disposals valued in GBP at transaction time.

**Components:**

- [ ] Matching engine: same-day, then 30-day, then s104 pooling; partial disposals pro-rata the pool cost
- [ ] Crypto-to-crypto disposal handling (both legs valued in GBP at ts)
- [ ] Fee treatment in allowable cost; withdrawal/deposit non-disposal handling
- [ ] Tax-year assignment (6 April boundaries) and per-year gain/loss summary
- [ ] **Fixture suite:** hand-built worked examples committed to the repo — including HMRC manual examples where they exist, plus the nasty orderings: buy/sell same day then rebuy within 30 days; partial disposal across a pool; disposal that spans a tax-year boundary; fee-only rows; ledger rows out of chronological order
- [ ] Flag-don't-compute path for income-type rows (staking, mining, airdrops)

**Done-when:** every fixture passes; a deliberately-reordered ledger produces identical output (determinism check); a staking row surfaces as flagged, not silently summed.

**If tight:** cut nothing here. This week is the one that cannot be thinned — if the engine is wrong, the product is harm, not help.

**Planning questions:**

1. Which HMRC worked examples go into fixtures verbatim? (List the manual page refs as you find them.)
2. Negligible-value claims and lost/stolen assets: flag-only like income, or out of v1 entirely? (Recommend out entirely, noted in the README's honesty section.)

---

### Week 3 — Upload pipeline, safety basics, backfill · applications start

**Track A — Upload + ingestion:**

- [ ] CSV upload endpoint: content-type + size limits, schema validation, malformed-file handling that fails with a useful message (never a 500)
- [ ] Kraken ledger parser → `transactions`, idempotent on `external_id` (re-upload doesn't duplicate)
- [ ] Celery valuation job: attach GBP at ts from the week-1 price source; backfill path for historical dates; cache aggressively
- [ ] Per-user rate limits on upload + chat (a free tier in front of your Anthropic key must not become someone else's bill)

**Track B — Applications (5–8 this week, non-negotiable):**

- [ ] UK hiring runs ~4–6 weeks per process; a 12-week runway still means applying with a working-but-imperfect repo now, across full-stack, AI-adjacent full-stack, and product-engineer titles. First screens rarely open the repo.

**Done-when:** a stranger's malformed CSV fails politely · your real ledger round-trips to a valued, matched, per-year summary · first application batch out.

**Planning questions:**

1. Free tier gate: anonymous single-upload calculator, or account-first? (Recommend anonymous calculator page as the top of funnel; account required to save.)
2. First batch weighting across the three role types — even thirds, or weighted where reply rates are best so far?

---

## Phase 2 — AI layer + product launch (weeks 4–7)

### Week 4 — RAG over the HMRC Cryptoassets Manual

**Components:**

- [ ] Ingest the manual: crawl/parse HTML → chunk (~800 tokens / 100 overlap) preserving section refs (CRYPTO##### page IDs) as metadata
- [ ] Embed (OpenAI) → pgvector; retrieve top-30 cosine → Cohere rerank → top-5
- [ ] Generate with Claude; citations are **manual page refs**, not bare chunk ids — a user can click through to GOV.UK
- [ ] Stream to the Next.js UI

**Done-when:** 10 real tax questions come back grounded with clickable HMRC citations; a question the manual doesn't answer says so instead of guessing.

**Planning questions:**

1. Chunk by HTML section boundaries or fixed token windows? (Recommend section-first, token-split only oversized sections — the manual's structure is the metadata.)
2. Manual-update detection: manual re-crawl for now, incremental re-index as a later stretch?

---

### Week 5 — Evals + flake-hardened CI gate + tracing + Core hardening · CV refresh · wave 2

**Track A — Evals:**

- [ ] Golden set, 20–30 pairs committed to the repo: easy / hard / adversarial / **no-answer-exists**, drawn from real tax edge cases (same-day, 30-day, transfer-vs-disposal confusions, questions the guidance is genuinely silent on)
- [ ] RAGAS baseline (faithfulness + answer relevance) into the README; Langfuse tracing on every request (cost + latency per call)
- [ ] **CI gate, flake-hardened (this replaces the old naive gate):** pin the judge model + temperature; cache judge responses for unchanged cases; hard-gate on a _deterministic_ subset (exact-match citation presence, refusal-on-no-answer cases); RAGAS faithfulness gates with buffer below baseline rather than a knife-edge, and reports otherwise. A gate that flakes gets ignored — that's the failure it exists to prevent, and knowing this trade-off is itself interview material.

**Track B — Core hardening (recovered from the flagship overlay — do not drop again):**

- [ ] JWT auth on FastAPI endpoints
- [ ] pytest suite with mocked price/FX responses so CI never depends on live rate limits — the single highest-leverage addition for the non-AI story

**Track C — Career:**

- [ ] CV/LinkedIn refresh with real project lines; 8–10 more applications; 3–5 targeted LinkedIn messages/week to people doing this work at UK companies

**Done-when:** a PR that breaks a deterministic case or drops faithfulness below threshold goes red — and stays green across three re-runs on unchanged code · auth on · mocked test suite in CI.

---

### Week 6 — Product layer + soft launch (the product-engineer week)

**Pre-launch checklist (blocking):**

- [ ] Privacy policy; "calculation aid, not tax advice" on every results surface; data-deletion path (button or documented email route); check ICO data-protection fee applicability now that you're processing strangers' data; confirm rate limits from week 3 hold under a small load test

**Launch components:**

- [ ] Landing page: the anonymous free calculator (one Kraken CSV, one tax year) as the door-opener; account to save/export
- [ ] PostHog from the first visit: funnel (land → upload → parsed → summary viewed → signup), plus event capture on parse failures with exchange-format guesses
- [ ] One feature flag on something real (e.g. the Q&A panel) so you have a genuine flag/experiment story
- [ ] Soft launch: 2–3 UK crypto communities — **read each community's self-promotion rules first** (r/UKPersonalFinance is strict); lead with the free calculator, not "try my app"

**Done-when:** a stranger you've never spoken to completes the funnel · the first parse-failure log tells you which exchange format is second.

**Planning questions:**

1. Which communities, in order? (Draft list, check rules, then commit.)
2. What single metric is the week's headline — completed summaries, or signups? (Pick one; it becomes the interview number.)

---

### Week 7 — Agentic depth (crunch week #1)

**Components:**

- [ ] Multi-tool, multi-step agent over: **ledger-query tool** (parameterised reads over transactions/disposals), **calc tool** (gain/loss, pool state, rule attribution), **guidance-retrieval tool** (the week-4 RAG as a tool)
- [ ] Orchestration loop with planning, reflection, retry, error recovery — Pydantic AI or LangGraph (decide here; Pydantic AI if the flows stay linear-ish, LangGraph if you find yourself wanting branches)
- [ ] Loop guardrails: max iterations, per-tool timeout, structured errors
- [ ] Read-only enforced at the tool layer, not by convention

**Done-when:** the canonical demo question ("how does the 30-day rule apply to these three disposals?") triggers a genuine multi-step run: ledger query → matching → guidance citation, visible in the Langfuse trace.

**If tight:** ship two tools fully rather than three thinly; guidance-retrieval is the one to defer since it exists standalone.

**Planning questions:**

1. Pydantic AI or LangGraph — decided which, and why (one sentence for interviews)?
2. Injection-detection approach for week 8: heuristics, small classifier, or cheap LLM-judge pass?

---

## Phase 3 — Hardening, economics, monetisation (weeks 8–10)

### Week 8 — Guardrails full + iterate off launch feedback

**Track A — Guardrails (the differentiator, now with real stakes):**

- [ ] Input: prompt-injection detection before user text reaches the model — including **injection via uploaded CSV fields**, which is your novel surface (a memo/description column carrying "ignore previous instructions" must be caught)
- [ ] Output: schema validation + moderation pass; numeric claims in answers must reconcile against the calc engine, not the model's arithmetic
- [ ] PII: detect/redact wallet addresses and account ids in logs so Langfuse traces are clean
- [ ] Data at rest: confirm encryption posture on Neon + any object storage of uploads

**Track B — Product iteration:** fix the top parse failures from week 6's logs; ship or kill based on the PostHog funnel, and write the decision down (these become the product-interview stories).

**Done-when:** a known injection string in a CSV memo field is caught and logged, not executed · one shipped fix and one explicit kill traceable to usage data.

---

### Week 9 — Production economics + README + write-up

- [ ] Anthropic prompt caching on system prompt + retrieved context (before/after in Langfuse)
- [ ] Model routing: Haiku for simple lookups, escalate multi-step; provider fallback on error; semantic cache on repeated guidance questions
- [ ] README to interview grade: problem, architecture diagram, calc-engine test philosophy, eval results, honest v1 scope cuts, what changes at 10x
- [ ] Blog post — strongest angle now: **"building an eval-gated RAG system over HMRC guidance"** or "what 50 strangers' CSVs taught me about crypto tax data". One post, published, linked from the CV.

**Done-when:** Langfuse shows the routing + caching cost drop as a clean before/after · post live.

---

### Week 10 — Stripe paid tier (stretch, but the highest-value stretch)

- [ ] £15–25 per tax year (pick after seeing week-6 funnel): unlock multi-year, PDF/CSV export for self-assessment, saved history
- [ ] Flask gets its real job: Stripe webhook receiver — one route, signature verification, idempotent fulfilment (this recovers and repurposes the old overlay's webhook item)
- [ ] Gate the paid features behind the existing flag system

**Done-when:** one real payment settles end-to-end in test-then-live mode. First revenue beats fifty free users in a product interview.

**If tight:** drop to weeks 11–12 spare hours; the January self-assessment deadline means demand arrives in autumn regardless of when you ship the paywall.

---

## Phase 4 — Interview engine (weeks 11–12, and ongoing from week 3)

- [ ] Primary time shifts to interviews; the repo stays alive — patch whatever a round exposes before the next similar round
- [ ] Rehearse out loud, one per room: **full-stack** — "design the ingestion + valuation pipeline" (idempotency, backfill, rate limits, mocked tests); **AI** — "design a RAG system for regulated guidance" (chunking by structure, citations, eval gating, injection-via-data); **product** — two or three stories in the shape _shipped X, watched the funnel, learned Y, cut Z_ (weeks 6 and 8 supply them)
- [ ] Stretch, spare hours only, chosen from interview feedback: MCP-wrap the guidance-Q&A tool · incremental manual re-indexing · finish anything thinned earlier
- [ ] Aim for 2+ live processes to negotiate from

---

## Crunch map

| Week  | Load               | Why                                             |
| ----- | ------------------ | ----------------------------------------------- |
| 1     | +½ day vs old plan | Docker + price-source verification              |
| 2     | heavy              | the calc engine — no parallel track, protect it |
| 3     | heavy              | upload + backfill + first applications          |
| 4     | normal             | RAG (corpus is clean HTML)                      |
| 5     | heavy              | evals + CI + auth/pytest + wave 2               |
| 6     | normal-but-public  | launch week; checklist is blocking              |
| 7     | ~1.5×              | agent — crunch week #1                          |
| 8     | ~1.5×              | guardrails + iteration — crunch week #2         |
| 9     | normal             | economics + writing                             |
| 10    | stretch            | Stripe                                          |
| 11–12 | interviews         | repo in maintenance                             |

## Cut order when a week overruns

**Never cut:** calc-engine correctness (wk 2) · price-history coverage (wk 1/3) · upload validation + rate limits (wk 3) · the pre-launch checklist (wk 6) · applications starting week 3.
**Cheap, keep:** Docker · PostHog · disclaimers · CI flake mitigations · JWT/pytest.
**Honest to describe if only partly built (first cuts):** hybrid retrieval (BM25 + RRF fusion — deliberately absent from the weekly plan above; add in spare hours or describe as the 10x answer) · production economics beyond prompt caching.
**Last in, first out:** Stripe (wk 10) · community-launch breadth beyond the first 2–3 · MCP wrap.

## Which story, which room (updated)

| They ask                                    | You show                                                                                                                         |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Walk me through a production Python service | FastAPI + Flask split, Celery valuation jobs, idempotent ingestion, JWT, Alembic, pytest with mocked APIs, `docker compose up`   |
| Walk me through your RAG project            | HMRC-manual RAG with section-ref citations, flake-hardened eval gate in CI, Langfuse traces                                      |
| Tell me about an agent you built            | three read-only tools, planned multi-step run on the 30-day-rule demo, and _why_ it's read-only                                  |
| How do you make an LLM app safe?            | injection-in (including via CSV data), schema + reconciliation out, PII-clean traces                                             |
| Tell me about a product decision you made   | the funnel-driven ship/kill pair from week 8, the Kraken-only and CGT-only scope cuts, [N] users, first revenue if wk 10 shipped |
| What would you change at 10x                | routing/fallback/semantic cache (built or described), hybrid retrieval, incremental re-index                                     |

---

_Open questions worth answering as you go (they sharpen the next pass): week 1's price-source verification result · week 2's HMRC fixture refs · week 3's free-tier gate · week 6's community list and headline metric · week 7's framework call. Everything previously open about corpus, demo question, write access, and exchange scope is settled in the decisions table — don't reopen it without new evidence._
