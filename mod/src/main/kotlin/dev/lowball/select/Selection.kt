package dev.lowball.select

import net.minecraft.world.item.ItemStack

/**
 * What the user has picked out for pricing.
 *
 * The selection is explicit and it persists across screens: pick two pieces out
 * of a chest, close it, open the trade window, add a third. Nothing is guessed
 * from what happens to be on screen.
 *
 * Items are keyed by the screen they came from plus the slot index, so clicking
 * the same slot twice deselects it and two identical items in different slots
 * stay separate. Item identity is not used as the key on purpose: stackables
 * have none, and two Hyperions in one chest are two entries.
 *
 * The screen part of the key comes from the server's own container id rather
 * than from a number minted when the screen was built. A screen is rebuilt
 * whenever the window is resized, and a minted id would change with it --
 * leaving the picked slots still in the set but no longer drawn as picked, and
 * clickable a second time as if they were new.
 */
object Selection {

    /**
     * How many items may be picked at once.
     *
     * A double chest is 54 slots and a trade window far fewer, so this is well
     * clear of any real selection. It is here because the armed tool turns
     * every click into a pick, and a user who walks across a chest with the
     * button held should end up with a full chest selected, not with a payload
     * the app has to defend itself against.
     */
    const val MAX_ITEMS: Int = 64

    /** True while clicks pick items instead of doing what they normally do. */
    @Volatile
    var armed: Boolean = false
        private set

    private val chosen = LinkedHashMap<String, SelectedItem>()

    val size: Int get() = synchronized(chosen) { chosen.size }

    fun toggleArmed(): Boolean {
        armed = !armed
        return armed
    }

    private fun key(screenId: String, slotIndex: Int): String = "$screenId#$slotIndex"

    fun isSelected(screenId: String, slotIndex: Int): Boolean =
        synchronized(chosen) { chosen.containsKey(key(screenId, slotIndex)) }

    /**
     * Slot index to its place in the pick order, 1-based, for one screen.
     *
     * Drawn in the corner of each picked slot. The app lists items in the order
     * they were picked, and this is what lets the user match a row on screen to
     * an item in the window without counting clicks backwards.
     *
     * Returned as a whole map rather than answered a slot at a time: the caller
     * is a render pass over every slot in the container, and asking per slot
     * would be a scan of the selection and a turn of this lock for each one, on
     * the render thread, every frame.
     */
    fun ordinalsFor(screenId: String): Map<Int, Int> = synchronized(chosen) {
        val prefix = "$screenId#"
        val ordinals = HashMap<Int, Int>(chosen.size)
        for ((position, entry) in chosen.keys.withIndex()) {
            if (!entry.startsWith(prefix)) continue
            val slot = entry.substring(prefix.length).toIntOrNull() ?: continue
            ordinals[slot] = position + 1
        }
        return ordinals
    }

    /** What one click on a slot did. */
    enum class Outcome { ADDED, REMOVED, UNREADABLE, FULL }

    /**
     * Add or remove one item.
     *
     * An item that will not encode is refused rather than added as a blank, and
     * says so, so the caller can tell the user instead of leaving them with a
     * slot that silently will not pick.
     */
    fun toggle(
        screenId: String,
        slotIndex: Int,
        stack: ItemStack,
        encoded: String?,
        source: String,
    ): Outcome {
        val id = key(screenId, slotIndex)
        synchronized(chosen) {
            if (chosen.remove(id) != null) return Outcome.REMOVED
            if (encoded == null) return Outcome.UNREADABLE
            if (chosen.size >= MAX_ITEMS) return Outcome.FULL
            chosen[id] = SelectedItem(
                key = id,
                slot = slotIndex,
                nbt = encoded,
                source = source,
                count = stack.count,
            )
            return Outcome.ADDED
        }
    }

    fun clear() {
        synchronized(chosen) { chosen.clear() }
    }

    /** A stable copy, in the order the items were picked. */
    fun snapshot(): List<SelectedItem> = synchronized(chosen) { chosen.values.toList() }
}

/** One picked item, already encoded for the wire. */
data class SelectedItem(
    val key: String,
    val slot: Int,
    val nbt: String,
    val source: String,
    val count: Int,
)
