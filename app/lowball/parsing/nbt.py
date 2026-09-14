"""Decoding SkyBlock item data.

Item payloads reach this app in two shapes and both arrive as gzipped NBT in
base64:

* from the mod, one serialised ItemStack per trade slot;
* from the Hypixel API, an ``item_bytes`` blob holding ``{"i": [ ... ]}``.

Since Minecraft 1.20.5 an ItemStack serialises to data components rather than
the old ``tag`` compound, so SkyBlock's ``ExtraAttributes`` now sits under
``components -> minecraft:custom_data``.  Rather than pin the parser to one
layout -- and re-break it at every content drop -- the extractors below search
the known locations and fall back to a bounded scan.
"""

from __future__ import annotations

import base64
import gzip
import io
import json
import re
from typing import Any

import nbtlib

#: Where a nested ExtraAttributes compound has lived, newest layout first.
EXTRA_ATTRIBUTE_PATHS: tuple[tuple[str, ...], ...] = (
    ("components", "minecraft:custom_data", "ExtraAttributes"),
    ("components", "custom_data", "ExtraAttributes"),
    ("tag", "ExtraAttributes"),
    ("ExtraAttributes",),
)

#: Where the custom data component itself lives.
CUSTOM_DATA_PATHS: tuple[tuple[str, ...], ...] = (
    ("components", "minecraft:custom_data"),
    ("components", "custom_data"),
)

#: A SkyBlock item id: upper case, no namespace.
SKYBLOCK_ID = re.compile(r"[A-Z][A-Z0-9_]*")

#: Keys that mark a compound as SkyBlock item data rather than anything else.
#: On a modern client Hypixel writes these straight into ``custom_data`` with
#: no ``ExtraAttributes`` wrapper around them -- the wrapper was an artefact of
#: the 1.8 ``tag`` compound and did not survive the move to components.
SKYBLOCK_MARKERS: frozenset[str] = frozenset(
    {
        "id",
        "uuid",
        "uId",
        "modifier",
        "enchantments",
        "upgrade_level",
        "petInfo",
        "rarity_upgrades",
        "hot_potato_count",
        "gems",
        "attributes",
        "timestamp",
    }
)

DISPLAY_NAME_PATHS: tuple[tuple[str, ...], ...] = (
    ("components", "minecraft:custom_name"),
    ("components", "custom_name"),
    ("tag", "display", "Name"),
    ("display", "Name"),
)

LORE_PATHS: tuple[tuple[str, ...], ...] = (
    ("components", "minecraft:lore"),
    ("components", "lore"),
    ("tag", "display", "Lore"),
    ("display", "Lore"),
)

COUNT_PATHS: tuple[tuple[str, ...], ...] = (("count",), ("Count",))


class NbtDecodeError(ValueError):
    """Raised when a payload is not readable as SkyBlock item NBT."""


def to_python(value: Any) -> Any:
    """Strip nbtlib wrapper types so results are JSON-safe and hashable."""
    if isinstance(value, (nbtlib.Compound, dict)):
        return {str(k): to_python(v) for k, v in value.items()}
    if isinstance(value, (nbtlib.List, list, tuple)):
        return [to_python(v) for v in value]
    if isinstance(value, (nbtlib.ByteArray, nbtlib.IntArray, nbtlib.LongArray)):
        return [int(v) for v in value]
    if isinstance(value, (nbtlib.String, str)):
        return str(value)
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    return value


def decompress(raw: bytes) -> bytes:
    """SkyBlock blobs are gzipped, but a few sources hand over raw NBT."""
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    return raw


def parse_nbt_bytes(raw: bytes) -> dict[str, Any]:
    """gzip+NBT bytes to a plain dict."""
    try:
        parsed = nbtlib.File.parse(io.BytesIO(decompress(raw)))
    except Exception as exc:  # noqa: BLE001 - any malformed blob lands here
        raise NbtDecodeError(f"could not parse NBT payload: {exc}") from exc
    return to_python(parsed)


def decode_b64(payload: str) -> dict[str, Any]:
    """base64 -> gzip -> NBT -> dict."""
    if not payload:
        raise NbtDecodeError("empty payload")
    try:
        raw = base64.b64decode(payload, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise NbtDecodeError(f"payload is not base64: {exc}") from exc
    return parse_nbt_bytes(raw)


def decode_item(payload: str) -> dict[str, Any]:
    """Decode a single item stack, unwrapping a one-element ``i`` list."""
    root = decode_b64(payload)
    items = root.get("i")
    if isinstance(items, list):
        return items[0] if items else {}
    return root


def decode_inventory(payload: str) -> list[dict[str, Any]]:
    """Decode the ``{"i": [...]}`` container the Hypixel API uses.

    Empty slots serialise as empty compounds; they are kept so slot indices
    stay meaningful to the caller.
    """
    root = decode_b64(payload)
    items = root.get("i")
    if isinstance(items, list):
        return [dict(entry) if isinstance(entry, dict) else {} for entry in items]
    return [root]


def dig(root: Any, path: tuple[str, ...]) -> Any:
    node = root
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def first_at(root: Any, paths: tuple[tuple[str, ...], ...]) -> Any:
    for path in paths:
        found = dig(root, path)
        if found is not None:
            return found
    return None


def _scan_for_key(node: Any, key: str, depth: int = 0) -> Any:
    """Bounded depth-first search for a key, used only as a last resort.

    A future content drop can move ``ExtraAttributes`` again.  Finding it late
    is better than failing to price the item, but the depth cap keeps a
    malformed blob from turning into a long walk.
    """
    if depth > 6:
        return None
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for value in node.values():
            found = _scan_for_key(value, key, depth + 1)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node[:64]:
            found = _scan_for_key(value, key, depth + 1)
            if found is not None:
                return found
    return None


def looks_like_skyblock(node: Any) -> bool:
    """Whether a compound is SkyBlock item data rather than some other blob.

    The giveaway is the id: SkyBlock writes ``HYPERION``, Minecraft writes
    ``minecraft:diamond_sword``. Matching on the mere presence of an ``id``
    would make every vanilla item stack look like SkyBlock data, since the
    stack itself has one.
    """
    if not isinstance(node, dict) or not node:
        return False
    item_id = node.get("id")
    if isinstance(item_id, str) and SKYBLOCK_ID.fullmatch(item_id):
        return True
    return len(SKYBLOCK_MARKERS & set(node)) >= 2


def extra_attributes(item: dict[str, Any]) -> dict[str, Any]:
    """The SkyBlock-specific compound, wherever this game version keeps it.

    Two shapes in the wild. The legacy one nests the attributes under an
    ``ExtraAttributes`` key; the one a modern client actually receives puts
    them straight into ``minecraft:custom_data``, because the wrapper belonged
    to the old ``tag`` compound and did not survive the move to components.

    Looking only for the wrapper is what made every real item arrive
    unpriceable, so both are handled and the bare form is recognised by its
    contents rather than by where it sits.
    """
    found = first_at(item, EXTRA_ATTRIBUTE_PATHS)
    if isinstance(found, dict) and found:
        return dict(found)

    custom = first_at(item, CUSTOM_DATA_PATHS)
    if looks_like_skyblock(custom):
        return dict(custom)

    found = _scan_for_key(item, "ExtraAttributes")
    if isinstance(found, dict) and found:
        return dict(found)

    # Last resort: some other layout entirely, recognised by its contents.
    scanned = _scan_for_skyblock(item)
    return dict(scanned) if scanned else {}


def _scan_for_skyblock(node: Any, depth: int = 0) -> dict[str, Any] | None:
    """Find a SkyBlock-looking compound anywhere shallow in the tree."""
    if depth > 4:
        return None
    if isinstance(node, dict):
        if looks_like_skyblock(node):
            return node
        for value in node.values():
            found = _scan_for_skyblock(value, depth + 1)
            if found is not None:
                return found
    elif isinstance(node, list):
        for value in node[:16]:
            found = _scan_for_skyblock(value, depth + 1)
            if found is not None:
                return found
    return None


def _text_of(value: Any) -> str:
    """Flatten a display name, which may be a plain string or a text component."""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        # Modern custom_name is often a JSON text component in a string.
        if text.startswith("{") or text.startswith("["):
            try:
                return _text_of(json.loads(text))
            except (ValueError, TypeError):
                return text
        return text
    if isinstance(value, dict):
        parts = [_text_of(value.get("text"))]
        for child in value.get("extra") or []:
            parts.append(_text_of(child))
        return "".join(parts)
    if isinstance(value, list):
        return "".join(_text_of(v) for v in value)
    return str(value)


def display_name(item: dict[str, Any]) -> str:
    return _text_of(first_at(item, DISPLAY_NAME_PATHS))


def lore_lines(item: dict[str, Any]) -> list[str]:
    raw = first_at(item, LORE_PATHS)
    if raw is None:
        return []
    if isinstance(raw, (str, dict)):
        raw = [raw]
    return [_text_of(line) for line in raw]


def stack_count(item: dict[str, Any]) -> int:
    value = first_at(item, COUNT_PATHS)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 1


def minecraft_id(item: dict[str, Any]) -> str | None:
    value = item.get("id")
    return str(value) if isinstance(value, str) else None


def is_empty(item: dict[str, Any] | None) -> bool:
    if not item:
        return True
    return not extra_attributes(item) and not minecraft_id(item)


def describe_payload(payload: str, *, max_depth: int = 3) -> str:
    """Explain what a payload actually contains, for when parsing it fails.

    The failure that matters is not "it did not decode" but "it decoded into
    something this parser does not recognise", and those need different fixes.
    This says which.
    """
    if not payload:
        return "empty payload"
    try:
        raw = base64.b64decode(payload, validate=False)
    except Exception as exc:  # noqa: BLE001
        return f"not base64: {exc}"

    head = raw[:2].hex()
    gzipped = raw[:2] == b"\x1f\x8b"
    try:
        root = parse_nbt_bytes(raw)
    except NbtDecodeError as exc:
        return f"{len(raw)} bytes, head={head}, gzip={gzipped}: {exc}"

    lines = [f"{len(raw)} bytes, gzip={gzipped}, root keys: {sorted(root)}"]
    lines.append(_outline(root, max_depth=max_depth))
    ea = extra_attributes(root if not isinstance(root.get("i"), list) else root["i"][0])
    lines.append(f"ExtraAttributes found: {bool(ea)}" + (f", id={ea.get('id')}" if ea else ""))
    return "\n".join(lines)


def _outline(node: Any, *, max_depth: int, depth: int = 0, prefix: str = "") -> str:
    """A shallow shape of a decoded tree: keys and types, not values."""
    pad = "  " * (depth + 1)
    if depth >= max_depth:
        return f"{pad}..."
    if isinstance(node, dict):
        parts = []
        for key, value in list(node.items())[:24]:
            if isinstance(value, (dict, list)):
                parts.append(f"{pad}{key}:")
                parts.append(_outline(value, max_depth=max_depth, depth=depth + 1))
            else:
                shown = str(value)
                if len(shown) > 60:
                    shown = shown[:57] + "..."
                parts.append(f"{pad}{key} = {shown}")
        return "\n".join(parts)
    if isinstance(node, list):
        if not node:
            return f"{pad}[]"
        return f"{pad}[{len(node)} entries]\n" + _outline(
            node[0], max_depth=max_depth, depth=depth + 1
        )
    return f"{pad}{node}"
