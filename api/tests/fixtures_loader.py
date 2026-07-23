"""Loader for declarative YAML golden fixtures (HMRC worked examples).

Test/eval infrastructure — deliberately NOT part of ``taxcalc``. The engine stays
pure, zero-I/O and zero-dependency; this loader (which does file I/O and pulls in
pydantic + pyyaml) lives with the tests.

Pydantic validates the fixture shape (``extra="forbid"`` so a mistyped key fails
loudly). Every money/quantity field is parsed from a STRING to ``Decimal`` and a
bare YAML float is REJECTED: YAML parses ``0.1`` as a binary float, which would
reintroduce the exact precision bug the engine works in ``Fraction`` to avoid.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict

from taxcalc.engine.matching import Acquisition, Disposal, MatchRule

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _to_decimal(v: Any) -> Decimal:
    # bool is an int subclass — reject explicitly, it is never a money value.
    if isinstance(v, bool):
        raise ValueError(f"expected a quoted number, got bool {v!r}")
    # A bare YAML float (0.1 -> 0.1000000000000000055…) silently loses precision;
    # fixtures MUST quote numbers as strings.
    if isinstance(v, float):
        raise ValueError(
            f"bare float {v!r} in fixture — quote it as a string to keep exact precision"
        )
    if isinstance(v, (str, int)):
        return Decimal(str(v))
    raise ValueError(f"cannot read Decimal from {type(v).__name__} {v!r}")


def _to_rule(v: Any) -> MatchRule:
    if isinstance(v, MatchRule):
        return v
    if isinstance(v, str):
        try:
            return MatchRule[v]  # by name, e.g. "SECTION_104"
        except KeyError:
            raise ValueError(
                f"unknown match rule {v!r}; expected one of {[r.name for r in MatchRule]}"
            ) from None
    raise ValueError(f"cannot read MatchRule from {type(v).__name__} {v!r}")


DecimalStr = Annotated[Decimal, BeforeValidator(_to_decimal)]
RuleName = Annotated[MatchRule, BeforeValidator(_to_rule)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AcquisitionSpec(_Strict):
    date: dt.date
    asset: str
    quantity: DecimalStr
    cost_gbp: DecimalStr

    def to_engine(self) -> Acquisition:
        return Acquisition(self.date, self.asset, self.quantity, self.cost_gbp)


class DisposalSpec(_Strict):
    date: dt.date
    asset: str
    quantity: DecimalStr
    proceeds_gbp: DecimalStr
    fee_gbp: DecimalStr

    def to_engine(self) -> Disposal:
        return Disposal(self.date, self.asset, self.quantity, self.proceeds_gbp, self.fee_gbp)


class MatchExpect(_Strict):
    rule: RuleName
    quantity: DecimalStr
    cost_gbp: DecimalStr


class DisposalExpect(_Strict):
    matches: list[MatchExpect]
    allowable_cost_gbp: DecimalStr
    gain_gbp: DecimalStr


class PoolExpect(_Strict):
    asset: str
    quantity: DecimalStr
    cost_gbp: DecimalStr


class FlagExpect(_Strict):
    code: str
    asset: str
    message: str | None = None  # optional; substring-matched when the fixture pins one


class Expect(_Strict):
    disposals: list[DisposalExpect]
    pools: list[PoolExpect]
    flags: list[FlagExpect] = []


class FixtureSpec(_Strict):
    name: str
    ref: str  # HMRC manual page, e.g. CRYPTO22251
    acquisitions: list[AcquisitionSpec]
    disposals: list[DisposalSpec]
    expect: Expect

    def acquisitions_engine(self) -> list[Acquisition]:
        return [a.to_engine() for a in self.acquisitions]

    def disposals_engine(self) -> list[Disposal]:
        return [d.to_engine() for d in self.disposals]


def load_fixture(path: Path) -> FixtureSpec:
    """Parse and validate one YAML fixture file."""
    data = yaml.safe_load(path.read_text())
    return FixtureSpec.model_validate(data)


def iter_fixture_paths() -> list[Path]:
    """All committed fixture files, in stable order."""
    return sorted(FIXTURES_DIR.glob("*.yaml"))
