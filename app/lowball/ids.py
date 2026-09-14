"""Identifier generation.  Opaque, unordered, and never parsed for meaning."""

from __future__ import annotations

import uuid


def new_id() -> str:
    return uuid.uuid4().hex


def new_uuid4() -> str:
    return str(uuid.uuid4())


def uid_of(item_uuid: str | None) -> str | None:
    """The SkyBlock ``uId``: the last 12 characters of an item UUID.

    This is the join key that survives an item being listed on the auction
    house, so it is how two sightings of the same physical item are matched.
    """
    if not item_uuid:
        return None
    stripped = item_uuid.replace("-", "")
    if len(stripped) < 12:
        return None
    return stripped[-12:]
