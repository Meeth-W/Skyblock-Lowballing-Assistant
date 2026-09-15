"""Seller names, remembered in memory.

An auction carries its seller as a UUID.  The name behind it is a request, and
:meth:`CoflnetClient.player_name` caches the answer in SQLite for a week -- but
a tooltip is drawn on the GUI thread and cannot wait for a coroutine to run, so
resolved names are mirrored here where a synchronous reader can see them.

Deliberately a plain dict rather than a class: there is one of these per
process and it holds a few dozen short strings.  Writes come from the asyncio
worker as lookups land and reads from the GUI thread as tooltips are drawn,
which needs no lock -- a dict assignment and a dict lookup are each a single
bytecode, and the worst a reader can see is the value from a moment ago.
"""

from __future__ import annotations

_names: dict[str, str] = {}


def remember(player_uuid: str | None, name: str | None) -> None:
    if player_uuid and name:
        _names[player_uuid] = name


def known(player_uuid: str | None) -> str | None:
    """The name, or None when it has not been looked up.

    Callers render the None case themselves rather than being handed a phrase
    for it: a tooltip and a status line want different words, and neither wants
    the raw UUID, which reads as a failure rather than as a question nobody has
    asked yet.
    """
    return _names.get(player_uuid or "")


def clear() -> None:
    _names.clear()
