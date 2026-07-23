"""HMRC worked-example fixtures run through the matching engine — the oracle check.

Each YAML in tests/fixtures/ is a declarative golden case transcribed verbatim from
HMRC guidance. One parametrized test runs the lot, so adding a worked example is a
data change (drop a .yaml), not a code change. These replace hand-picked golden
values with HMRC's own numbers.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from fixtures_loader import FixtureSpec, iter_fixture_paths, load_fixture
from taxcalc.engine.matching import match_disposals


@pytest.mark.parametrize("path", iter_fixture_paths(), ids=lambda p: p.stem)
def test_hmrc_fixture(path: Path) -> None:
    fx = load_fixture(path)
    outcome = match_disposals(fx.acquisitions_engine(), fx.disposals_engine())

    # Disposals — the engine sorts by (date, asset); the fixture lists them the same.
    assert len(outcome.disposals) == len(fx.expect.disposals)
    for got, want in zip(outcome.disposals, fx.expect.disposals, strict=True):
        assert [m.rule for m in got.matches] == [m.rule for m in want.matches]
        for gm, wm in zip(got.matches, want.matches, strict=True):
            assert gm.quantity == wm.quantity  # Fraction == Decimal holds in Python
            assert gm.cost_gbp == wm.cost_gbp
        assert got.allowable_cost_gbp == want.allowable_cost_gbp
        assert got.gain_gbp == want.gain_gbp

    # Pools — carried forward per asset.
    assert {p.asset for p in fx.expect.pools} == set(outcome.pools)
    for want_pool in fx.expect.pools:
        got_pool = outcome.pools[want_pool.asset]
        assert got_pool.quantity == want_pool.quantity
        assert got_pool.cost_gbp == want_pool.cost_gbp

    # Flags — code+asset must match; message substring-checked when the fixture pins one.
    assert len(outcome.flags) == len(fx.expect.flags)
    got_flags = {(f.code, f.asset): f.message for f in outcome.flags}
    for want_flag in fx.expect.flags:
        key = (want_flag.code, want_flag.asset)
        assert key in got_flags
        if want_flag.message is not None:
            assert want_flag.message in got_flags[key]


def test_bare_float_in_fixture_is_rejected() -> None:
    """The precision guard: a bare YAML float must fail loudly, never coerce silently."""
    bad = {
        "name": "bad",
        "ref": "x",
        "acquisitions": [
            {"date": "2018-01-01", "asset": "A", "quantity": 100.0, "cost_gbp": "1000"}
        ],
        "disposals": [],
        "expect": {"disposals": [], "pools": [], "flags": []},
    }
    with pytest.raises(ValidationError):
        FixtureSpec.model_validate(bad)
