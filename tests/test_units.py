"""R-042: a unit symbol reads into a factor to SI, or into nothing, and never into a wrong factor."""

from __future__ import annotations

import pytest
from planteo import Dimension

from copela.units import scale

TIME = {"time": 1}


@pytest.mark.parametrize(
    ("symbol", "axes", "factor"),
    [
        ("s", TIME, 1.0),
        ("min", TIME, 60.0),
        ("minutes", TIME, 60.0),
        ("h", TIME, 3600.0),
        ("hours", TIME, 3600.0),
        ("ms", TIME, 1e-3),
        ("day", TIME, 86400.0),
        ("month", TIME, 365.25 * 86400 / 12),
        ("yr", TIME, 365.25 * 86400),
        ("L", {"length": 3}, 1e-3),
        ("mL", {"length": 3}, 1e-6),
        ("m3", {"length": 3}, 1.0),
        ("m^3", {"length": 3}, 1.0),
        ("g", {"mass": 1}, 1e-3),
        ("kg", {"mass": 1}, 1.0),
        ("t", {"mass": 1}, 1e3),
        ("mg/L", {"mass": 1, "length": -3}, 1e-3),
        ("g/L", {"mass": 1, "length": -3}, 1.0),
        ("kg*(L)^-1", {"mass": 1, "length": -3}, 1e3),
        ("L/min", {"length": 3, "time": -1}, 1e-3 / 60),
        ("1/h", {"time": -1}, 1 / 3600),
        ("(min)^-1", {"time": -1}, 1 / 60),
        ("µF", {"mass": -1, "length": -2, "time": 4, "current": 2}, 1e-6),
        ("uF", {"mass": -1, "length": -2, "time": 4, "current": 2}, 1e-6),
        ("kΩ", {"mass": 1, "length": 2, "time": -3, "current": -2}, 1e3),
        ("mV", {"mass": 1, "length": 2, "time": -3, "current": -1}, 1e-3),
        ("N*s/m", {"mass": 1, "time": -1}, 1.0),
        ("mol/L", {"amount": 1, "length": -3}, 1e3),
        ("M", {"amount": 1, "length": -3}, 1e3),
        ("USD/month", {"currency": 1, "time": -1}, 12 / (365.25 * 86400)),
        ("people", {"count": 1}, 1.0),
        ("thousand rabbits", {"count": 1}, 1e3),
        ("1", {}, 1.0),
        ("%", {}, 1e-2),
    ],
)
def test_a_symbol_reads_into_its_factor_to_si(symbol, axes, factor) -> None:
    read = scale(Dimension.of(symbol, **axes))
    assert read is not None, symbol
    assert read.factor == pytest.approx(factor, rel=1e-12)
    assert read.offset == 0.0


def test_celsius_is_affine_and_a_rate_per_degree_is_not() -> None:
    assert scale(Dimension.of("°C", temperature=1)).to_si(20.0) == pytest.approx(293.15)  # type: ignore[union-attr]
    assert scale(Dimension.of("K", temperature=1)).to_si(293.15) == pytest.approx(293.15)  # type: ignore[union-attr]
    per_minute = scale(Dimension.of("°C/min", temperature=1, time=-1))
    assert per_minute is not None and per_minute.offset == 0.0


@pytest.mark.parametrize(
    ("symbol", "axes"),
    [
        ("", TIME),  # no symbol: nothing to read
        ("min", {"length": 1}),  # the symbol says time, the dimension says length
        ("C", {"temperature": 1}),  # C is a coulomb, so as a temperature it is not trusted
        ("L/min", {"length": 3}),  # a rate declared as a volume
        ("fortnights", {"count": 1, "time": 1}),  # an unknown word cannot also be a time
        ("kg)/(", {"mass": 1}),  # not a symbol
    ],
)
def test_a_symbol_that_cannot_be_trusted_reads_into_nothing(symbol, axes) -> None:
    assert scale(Dimension.of(symbol, **axes)) is None
