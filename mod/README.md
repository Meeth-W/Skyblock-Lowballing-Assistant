# Lowball Uplink (Minecraft mod)

Read-only capture of trade screen contents, forwarded to the desktop app over a
loopback WebSocket.

## What it does

1. Puts three buttons on every container screen — your inventory, a chest, the
   trade window: **Select items**, **Send (n)**, **Clear**.
2. While the tool is armed, a click on a slot picks that item instead of doing
   what it normally would. Click a picked slot again to drop it.
3. **Send** transmits the picked set to the desktop app.
4. Watches chat for the server's own `Trade completed with …` announcement and
   forwards what it says changed hands.
5. Keeps an outbound WebSocket open to `ws://127.0.0.1:8765`.

The selection persists across screens, so you can pick two things out of a
chest, close it, open a trade and add a third. Sending is a separate act rather
than something that happens on every click: picking is fiddly and often
involves changing your mind, and the app should see the set you settled on
rather than every intermediate state of it.

There is no keybind. The buttons are the whole interface.

### Why selection rather than detection

The first version tried to recognise the trade window by its title and work out
which half of it belonged to whom. Both were guesses, and both were wrong in
practice. Asking the user which items matter removes the guessing entirely, and
it buys a feature for free: the same tool price-checks a chest.

### How an item is encoded

Two routes, tried in order. The first asks `ItemStack.CODEC` to encode the
whole stack. The second builds the payload by hand from the three things the
app actually reads — `custom_data`, the display name and the lore — and is used
whenever the codec declines *or comes back without SkyBlock's data in it*.

That second route exists because the first build shipped without it, and items
reached the app as unpriceable blanks. The codec path fails by returning an
empty result rather than throwing, so nothing anywhere reported a problem; the
app just silently showed nothing. The hand-built payload cannot drift, because
its shape is written out in `NbtSerializer.buildPayload` rather than inherited
from whatever the codec does this version — and that function is exercised
against the app's real parser in `test_mod_contract.py`.

### Why chat rather than an inventory diff

Hypixel already announces the settled trade:

```
Trade completed with [MVP+] Thxnndrr!
 + 1x Ancient Warden Helmet
 - 390M coins
```

That is better ground truth than diffing the inventory afterwards. The diff had
to guess at timing, could not tell a trade from any other inventory change in
the same tick, and scraped the price off the scoreboard sidebar. The server
states the figure outright.

What chat does not carry is item NBT, only display names — so the mod reports
names and the app matches them against what it was already pricing.

## What it does not do, and will not

The mod sends **zero** packets to the server. No chat, no commands, no
auto-listing, no key bound to any in-game action.

Hypixel's rules prohibit external software automating a player gameplay action,
and macros — one input producing one in-game action — are banned separately.
The select tool is the opposite of a macro: while armed, a click over a slot is
*swallowed*, so it causes **no** in-game action where it normally would cause
one. Clicks that are not over a slot pass through untouched, while the tool is
disarmed the mod does not touch input at all, and no key is bound to anything.

It does now render — a button and an outline around picked slots. Rendering is
client-side and sends nothing.

There is one mixin, `ContainerScreenAccessor`. It is an `@Accessor` and nothing
else: three read-only getters for `hoveredSlot`, `leftPos` and `topPos`. It
intercepts no method and changes nothing the game does. It exists because
Minecraft has already worked out which slot the cursor is over, and recomputing
that would mean hardcoding the vanilla GUI layout.

The desktop app has no channel back into the game. `UplinkClient` has a listener
that discards every frame it receives, and the app's server has no encoder and
never writes.

## Building

```bash
./gradlew build          # both configured versions
./gradlew :26.1.2:build  # just one
```

Built and verified against Minecraft 26.1.2 and 26.2. Output jars:

    versions/26.1.2/build/libs/lowball-26.1.2-0.1.0+26.1.2.jar
    versions/26.2/build/libs/lowball-26.2-0.1.0+26.2.jar

### Why the build looks unusual

From 26.1 the game ships **fully unobfuscated**. Its version manifest carries
no `client_mappings` entry at all, because there is nothing to deobfuscate.
Three consequences, each of which is a real trap:

- the plugin is `net.fabricmc.fabric-loom`, **not** `fabric-loom-remap`;
- there is **no `mappings` dependency**. Asking for `officialMojangMappings()`
  fails outright, and an empty layered spec fails differently;
- dependencies are plain `implementation`, not `modImplementation`, because
  nothing is being remapped.

It also means the source uses **Mojang names, not Yarn**: `Minecraft` rather
than `MinecraftClient`, `net.minecraft.world.item.ItemStack` rather than
`net.minecraft.item.ItemStack`, `CompoundTag` rather than `NbtCompound`, and
`KeyMapping` rather than `KeyBinding`. Anything written from a Yarn-era
tutorial will not compile.

Java 25 is required by both targets.

## Multi-version

Stonecutter is configured from the first commit rather than retrofitted.
Hypixel SkyBlock permits only the two most recent content drops, so 26.1.2 sits
near the bottom of the supported window and will be cut when 26.3 ships. Adding
a version is one line in `settings.gradle.kts` plus its coordinates in
`build.gradle.kts` — which is only true because the layout exists before it is
needed.

26.1 was the first release under the `year.drop.hotfix` scheme and ships fully
unobfuscated, so there is no Yarn remapping step.

## Configuration

The port and the capture key, and nothing else. Every decision that matters is
made in the desktop app, which is what keeps the quarterly version bumps cheap.
The capture key is unbound by default; set it in Controls.

## Layout assumptions

Two things depend on how Hypixel draws its trade window, and both are isolated
so they are cheap to correct:

- `Config.TRADE_TITLE_PATTERNS` — how a trade screen is recognised.
- `Config.THEIR_SIDE_FIRST_COLUMN` — which half of the window is theirs.

Every slot is sent either way, so a wrong split mislabels sides rather than
losing data.
