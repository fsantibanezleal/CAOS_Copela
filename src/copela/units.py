"""The scale of a unit symbol, so two documents written in different units can be compared.

planteo carries a dimension as an exponent vector plus the symbol it was written in, and compares
only the vector: minutes and hours are both time. That is right for a dimensional check and not
enough for a comparison of values. A candidate that integrates in hours where the reference
integrates in minutes asks its question at 1 where the reference asks at 60, and without a scale the
two were never compared, so a correct formalization could not be found faithful.

This module reads a symbol into a factor to SI for a closed vocabulary, and returns nothing for a
symbol it cannot read, which callers take as "compare the raw values", the behaviour before it
existed. A reading is accepted only when the exponents it implies are the exponents the document
declared, so a symbol that says one thing and a dimension that says another is not trusted.

Temperature in degrees Celsius is affine, not a scale: a value converts with an offset, and only a
symbol that is exactly one Celsius token is read that way. A rate per degree is a scale either way.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

from planteo import Dimension
from planteo.dimensions import AXES

_E = {axis: i for i, axis in enumerate(AXES)}


def _v(**axes: int) -> tuple[Fraction, ...]:
    out = [Fraction(0)] * len(AXES)
    for axis, exponent in axes.items():
        out[_E[axis]] = Fraction(exponent)
    return tuple(out)


_YEAR = 365.25 * 86400.0

#: Unit tokens to (factor to SI, exponents). Prefixes are applied separately, and only to the
#: tokens marked as taking one.
_UNITS: dict[str, tuple[float, tuple[Fraction, ...]]] = {
    # time
    "s": (1.0, _v(time=1)),
    "min": (60.0, _v(time=1)),
    "h": (3600.0, _v(time=1)),
    "hr": (3600.0, _v(time=1)),
    "d": (86400.0, _v(time=1)),
    "day": (86400.0, _v(time=1)),
    "wk": (604800.0, _v(time=1)),
    "week": (604800.0, _v(time=1)),
    "month": (_YEAR / 12.0, _v(time=1)),
    "mo": (_YEAR / 12.0, _v(time=1)),
    "yr": (_YEAR, _v(time=1)),
    "year": (_YEAR, _v(time=1)),
    # length, area, volume
    "m": (1.0, _v(length=1)),
    "L": (1e-3, _v(length=3)),
    "l": (1e-3, _v(length=3)),
    "litre": (1e-3, _v(length=3)),
    "liter": (1e-3, _v(length=3)),
    # mass
    "g": (1e-3, _v(mass=1)),
    "t": (1e3, _v(mass=1)),
    "tonne": (1e3, _v(mass=1)),
    # amount
    "mol": (1.0, _v(amount=1)),
    "M": (1e3, _v(amount=1, length=-3)),
    # electrical and mechanical
    "A": (1.0, _v(current=1)),
    "V": (1.0, _v(mass=1, length=2, time=-3, current=-1)),
    "ohm": (1.0, _v(mass=1, length=2, time=-3, current=-2)),
    "Ω": (1.0, _v(mass=1, length=2, time=-3, current=-2)),
    "F": (1.0, _v(mass=-1, length=-2, time=4, current=2)),
    "H": (1.0, _v(mass=1, length=2, time=-2, current=-2)),
    "C": (1.0, _v(current=1, time=1)),
    "N": (1.0, _v(mass=1, length=1, time=-2)),
    "J": (1.0, _v(mass=1, length=2, time=-2)),
    "W": (1.0, _v(mass=1, length=2, time=-3)),
    "Pa": (1.0, _v(mass=1, length=-1, time=-2)),
    "Hz": (1.0, _v(time=-1)),
    # temperature, as a scale; the affine reading is handled on its own below
    "K": (1.0, _v(temperature=1)),
    "°C": (1.0, _v(temperature=1)),
    "degC": (1.0, _v(temperature=1)),
    # currency: only the one the corpora use
    "USD": (1.0, _v(currency=1)),
    # pure numbers
    "%": (1e-2, _v()),
    "hundred": (1e2, _v()),
    "thousand": (1e3, _v()),
    "million": (1e6, _v()),
    "billion": (1e9, _v()),
}

#: Plural and long forms, read as the token they name.
_ALIASES = {
    "sec": "s", "second": "s", "seconds": "s", "secs": "s",
    "mins": "min", "minute": "min", "minutes": "min",
    "hrs": "hr", "hour": "h", "hours": "h",
    "days": "day", "weeks": "week", "months": "month",
    "yrs": "yr", "years": "year",
    "metre": "m", "meter": "m", "metres": "m", "meters": "m",
    "litres": "litre", "liters": "liter",
    "gram": "g", "grams": "g", "kilogram": "kg", "kilograms": "kg",
    "tonnes": "tonne",
    "volt": "V", "volts": "V", "amp": "A", "ampere": "A", "amperes": "A",
    "ohms": "ohm", "farad": "F", "henry": "H", "newton": "N", "newtons": "N",
    "joule": "J", "joules": "J", "watt": "W", "watts": "W", "kelvin": "K",
    "celsius": "°C", "ºC": "°C", "℃": "°C",
}

_PREFIXES = {"n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3, "c": 1e-2, "d": 1e-1, "k": 1e3, "M": 1e6, "G": 1e9}
#: Tokens a prefix may attach to. Not the time words: "mh" is not a thing anyone means.
_PREFIXABLE = {"s", "m", "L", "l", "g", "mol", "A", "V", "ohm", "Ω", "F", "H", "C", "N", "J", "W", "Pa", "Hz"}

_CELSIUS = {"°C", "degC", "celsius", "ºC", "℃"}
#: Words that stand for a count or for nothing: a population in "people" is a count of people.
_COUNT_WORDS = re.compile(r"^[A-Za-z]+$")

_TOKEN = re.compile(r"\s*(\(|\)|\*|/|·|\^|-?\d+(?:\.\d+)?(?:/\d+)?|[^\s()*/·^]+)")


@dataclass(frozen=True, slots=True)
class Scale:
    """``si = value * factor + offset``."""

    factor: float
    offset: float = 0.0

    def to_si(self, value: float) -> float:
        return value * self.factor + self.offset


def _token(word: str, counts: bool) -> tuple[float, tuple[Fraction, ...]] | None:
    word = _ALIASES.get(word, word)
    if word in ("1", ""):
        return 1.0, _v()
    # A trailing integer is an exponent written without a caret: m3, s2.
    match = re.fullmatch(r"(.*?[^\d])(\d)", word)
    if match and match.group(1) not in ("", "-"):
        inner = _token(match.group(1), counts)
        if inner is None:
            return None
        power = int(match.group(2))
        return inner[0] ** power, tuple(e * power for e in inner[1])
    if word in _UNITS:
        return _UNITS[word]
    for prefix, factor in _PREFIXES.items():
        if word.startswith(prefix) and word[len(prefix):] in _PREFIXABLE:
            base, exponents = _UNITS[word[len(prefix):]]
            return factor * base, exponents
    if _COUNT_WORDS.match(word):
        return (1.0, _v(count=1)) if counts else (1.0, _v())
    return None


def _parse(symbol: str, counts: bool) -> tuple[float, tuple[Fraction, ...]] | None:
    tokens = [t for t in _TOKEN.findall(symbol) if t.strip()]
    position = 0

    def factor() -> tuple[float, tuple[Fraction, ...]] | None:
        nonlocal position
        if position >= len(tokens):
            return None
        token = tokens[position]
        if token == "(":
            position += 1
            inner = expression()
            if inner is None or position >= len(tokens) or tokens[position] != ")":
                return None
            position += 1
            value = inner
        elif token in (")", "*", "/", "·", "^"):
            return None
        else:
            position += 1
            try:
                number = float(Fraction(token))
            except (ValueError, ZeroDivisionError):
                value = _token(token, counts)
            else:
                value = (number, _v())
            if value is None:
                return None
        if position < len(tokens) and tokens[position] == "^":
            position += 1
            if position >= len(tokens):
                return None
            try:
                power = Fraction(tokens[position])
            except (ValueError, ZeroDivisionError):
                return None
            position += 1
            value = (value[0] ** float(power), tuple(e * power for e in value[1]))
        return value

    def expression() -> tuple[float, tuple[Fraction, ...]] | None:
        nonlocal position
        left = factor()
        while left is not None and position < len(tokens) and tokens[position] != ")":
            # Two units side by side multiply: "kg m", "thousand rabbits".
            operator = tokens[position] if tokens[position] in ("*", "/", "·") else "*"
            if tokens[position] in ("*", "/", "·"):
                position += 1
            right = factor()
            if right is None:
                return None
            sign = -1 if operator == "/" else 1
            left = (
                left[0] * right[0] ** sign,
                tuple(a + sign * b for a, b in zip(left[1], right[1], strict=True)),
            )
        return left

    result = expression()
    if result is None or position != len(tokens):
        return None
    return result


def scale(dimension: Dimension) -> Scale | None:
    """The factor from a value in ``dimension``'s unit to SI, or None when the symbol cannot be read
    or reads as a dimension other than the one declared."""
    symbol = dimension.symbol.strip()
    if not symbol:
        return None
    if symbol in _CELSIUS and dimension.exponents == _v(temperature=1):
        return Scale(1.0, 273.15)
    for counts in (True, False):
        parsed = _parse(symbol, counts)
        if parsed is not None and parsed[1] == tuple(dimension.exponents):
            return Scale(parsed[0])
    return None


__all__ = ["Scale", "scale"]
