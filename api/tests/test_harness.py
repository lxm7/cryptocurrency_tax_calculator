"""Smoke test: proves the uv / pytest / src-layout toolchain is wired.

Real engine red-green starts in step 3.
"""

import taxcalc


def test_package_importable() -> None:
    assert taxcalc.__name__ == "taxcalc"
    assert taxcalc.__version__ == "0.1.0"
