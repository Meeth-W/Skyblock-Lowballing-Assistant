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
 */
object Selection {

    /** True while clicks pick items instead of doing what they normally do. */
    @Volatile
    var armed: Boolean = false
        private set

    private val chosen = LinkedHashMap<String, SelectedItem>()

    val size: Int get() = synchronized(chosen) { chosen.size }

    val isEmpty: Boolean get() = size == 0

    fun setArmed(value: Boolean) {
        armed = value
    }

    fun toggleArmed(): Boolean {
        armed = !armed
        return armed
    }

    fun key(screenId: String, slotIndex: Int): String = "$screenId#$slotIndex"

    fun isSelected(screenId: String, slotIndex: Int): Boolean =
        synchronized(chosen) { chosen.containsKey(key(screenId, slotIndex)) }

    /**
     * Add or remove one item.
     *
     * Returns true when it is now selected, false when the click removed it.
     * An item that will not encode is refused rather than added as a blank.
     */
    fun toggle(
        screenId: String,
        slotIndex: Int,
        stack: ItemStack,
        encoded: String?,
        source: String,
    ): Boolean {
        val id = key(screenId, slotIndex)
        synchronized(chosen) {
            if (chosen.remove(id) != null) return false
            if (encoded == null) return false
            chosen[id] = SelectedItem(
                key = id,
                slot = slotIndex,
                nbt = encoded,
                source = source,
                count = stack.count,
            )
            return true
        }
    }

    fun clear() {
        synchronized(chosen) { chosen.clear() }
    }

    /** A stable copy, in the order the items were picked. */
    fun snapshot(): List<SelectedItem> = synchronized(chosen) { chosen.values.toList() }

    /** Drop everything picked from one screen, used when that screen closes. */
    fun forget(screenId: String): Int = synchronized(chosen) {
        val prefix = "$screenId#"
        val gone = chosen.keys.filter { it.startsWith(prefix) }
        gone.forEach(chosen::remove)
        gone.size
    }
}

/** One picked item, already encoded for the wire. */
data class SelectedItem(
    val key: String,
    val slot: Int,
    val nbt: String,
    val source: String,
    val count: Int,
)
