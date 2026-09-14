"""Coin formatting and parsing.

Coins are integers everywhere in this codebase.  They are never floats: a
rounding drift of a few coins per trade compounds into a wrong P&L, and the
ledger has to reconcile against numbers the user reads in game.

Display rule (Part 13.3): coin values format as ``847.2M`` / ``1.24B``, never
raw digits.  A mantissa of 100 or more keeps one decimal, anything smaller
keeps two, which is what makes ``847.2M`` and ``1.24B`` sit at the same width.
"""

from __future__ import annotations

import re

_UNITS: tuple[tuple[int, str], ...] = (
    (1_000_000_000_000, "T"),
    (1_000_000_000, "B"),
    (1_000_000, "M"),
    (1_000, "k"),
)

_SUFFIX_VALUE = {"t": 10**12, "b": 10**9, "m": 10**6, "k": 10**3, "": 1}

_PARSE_RE = re.compile(
    r"""^\s*
        (?P<sign>[-+\u2212])?\s*
        (?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)
        \s*
        (?P<suffix>[tTbBmMkK])?
        \s*(?:coins?)?\s*$""",
    re.VERBOSE,
)


def format_coins(value: int | float | None, *, placeholder: str = "\u2014") -> str:
    """``847200000`` -> ``847.2M``.  ``None`` renders as an em dash."""
    if value is None:
        return placeholder
    n = float(value)
    sign = "-" if n < 0 else ""
    n = abs(n)
    for threshold, suffix in _UNITS:
        if n >= threshold:
            mantissa = n / threshold
            # 847.2M keeps one decimal; 1.24B keeps two.  Both are 5 glyphs wide.
            decimals = 1 if mantissa >= 100 else 2
            text = f"{mantissa:.{decimals}f}"
            # 999.95M would render as 1000.0M; promote it to the next unit up.
            if float(text) >= 1000:
                continue
            return f"{sign}{text}{suffix}"
    return f"{sign}{int(round(n)):,}"


def format_coins_exact(value: int | float | None, *, placeholder: str = "\u2014") -> str:
    """Full precision, for tooltips.  ``847200000`` -> ``847,200,000``."""
    if value is None:
        return placeholder
    return f"{int(round(float(value))):,}"


def format_signed(value: int | float | None, *, placeholder: str = "\u2014") -> str:
    """Profit and loss figures always carry their sign."""
    if value is None:
        return placeholder
    if value > 0:
        return "+" + format_coins(value)
    return format_coins(value)


def format_pct(fraction: float, *, decimals: int = 1, signed: bool = False) -> str:
    """``0.103`` -> ``10.3%``.  Takes a fraction, not a percentage."""
    pct = fraction * 100.0
    body = f"{pct:.{decimals}f}%"
    if signed and pct > 0:
        return "+" + body
    return body


def parse_coins(text: str) -> int:
    """Parse what a user types into the 'Bought at ___' field.

    Accepts ``847.2m``, ``1.24B``, ``847,200,000``, ``847200000 coins``.
    Raises :class:`ValueError` on anything else rather than guessing, because a
    silently misparsed cost basis corrupts every downstream margin.
    """
    match = _PARSE_RE.match(text or "")
    if not match:
        raise ValueError(f"cannot read {text!r} as a coin amount")
    num = float(match.group("num").replace(",", ""))
    unit = _SUFFIX_VALUE[(match.group("suffix") or "").lower()]
    sign = -1 if match.group("sign") in {"-", "\u2212"} else 1
    return sign * int(round(num * unit))


def value_bucket(coins: int) -> str:
    """Coarse value band used for hierarchical shrinkage in the offer model.

    The buckets are deliberately wide.  They exist so a Hyperion with no
    personal history can borrow from other 500M-plus items, not to slice thin
    data even thinner.
    """
    n = abs(int(coins))
    if n < 1_000_000:
        return "<1M"
    if n < 10_000_000:
        return "1-10M"
    if n < 50_000_000:
        return "10-50M"
    if n < 100_000_000:
        return "50-100M"
    if n < 500_000_000:
        return "100-500M"
    if n < 1_000_000_000:
        return "500M-1B"
    return ">1B"
