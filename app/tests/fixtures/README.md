# Parser fixtures

Each item is stored twice, in both layouts the parser has to read:

- `*.legacy.b64` — the pre-1.20.5 `tag` compound. Still what the Hypixel API
  returns in `item_bytes`.
- `*.component.b64` — the 1.20.5+ data-component layout, with `ExtraAttributes`
  under `minecraft:custom_data`. This is what the mod captures on 26.1.

`test_parsing.py` asserts that both layouts of the same item produce an
identical signature. That equivalence is the regression test that matters: it
is what catches a content drop moving the data again.

## real_hyperion_fabled.component.b64 is a real capture

That one came off a live client through the mod, and it is the fixture that
matters most. It is a 10-star Fabled Hyperion with Chimera V, three ability
scrolls and two perfect gems.

It exposed a bug none of the modelled fixtures could: on a modern client
Hypixel writes the SkyBlock attributes **straight into
`minecraft:custom_data`**, with no `ExtraAttributes` wrapper. Every hand-built
fixture had the wrapper, because that is what the old 1.8 `tag` compound used
— so both halves of the app agreed with each other and disagreed with the
game. Every real item arrived unpriceable.

The lesson is worth keeping: a fixture written by the same person who wrote the
parser tests only that they are consistent.

## The rest are modelled, not captured

They are built from the documented shape of SkyBlock item data. They are good
enough to pin parser behaviour, but they cannot catch a field this codebase
does not know exists.

**Add more real captures as you go.** Run `python -m lowball --listen`, select
an item, and any payload that fails to parse is written to `failed-items/`
ready to drop in here. Worth collecting: a Golden Dragon, an attribute-shard
armour set, a skinned and dyed item, and anything stackable.

Regenerate the modelled set with:

    python build_fixtures.py
