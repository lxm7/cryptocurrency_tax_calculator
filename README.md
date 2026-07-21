# Cryptocurrency CGT tax calculator

UK crypto **Capital Gains Tax calculation and reporting aid** — turns a Kraken
ledger export into per-tax-year gain/loss figures using HMRC share-matching
(same-day → 30-day → Section 104 pool), with an assistant that explains each
treatment against cited HMRC guidance.

## Dev quickstart

```bash
uv sync --project api                 # provisions Python 3.13, installs dev deps
uv run --project api pytest -q        # tests
uv run --project api ruff check api   # lint
uv run --project api mypy api/src     # types (strict)
```
