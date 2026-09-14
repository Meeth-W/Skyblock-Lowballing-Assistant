package dev.lowball.capture

import dev.lowball.select.SelectedItem

/**
 * Hand-rolled JSON for the four messages this mod sends.
 *
 * A serialisation library would be one more dependency to re-resolve at every
 * Minecraft version bump, for four fixed shapes with no user-supplied
 * structure. The only values that are not already base64 or numeric are player
 * names, item names and timestamps, and [escape] handles those.
 */
object Messages {

    fun hello(modVersion: String, mcVersion: String, uuid: String?, name: String?): String =
        buildString {
            append("""{"type":"hello","mod_version":"""")
            append(escape(modVersion))
            append("""","mc_version":"""")
            append(escape(mcVersion))
            append("""","player_uuid":""")
            append(quoteOrNull(uuid))
            append(""","player_name":""")
            append(quoteOrNull(name))
            append("}")
        }

    /**
     * The items the user has picked out, in the order they picked them.
     *
     * The whole selection is sent on every change rather than a delta, so a
     * dropped message cannot leave the two sides disagreeing about what is
     * selected.
     */
    fun itemsSelected(items: List<SelectedItem>, capturedAt: String): String = buildString {
        append("""{"type":"items_selected","items":[""")
        items.forEachIndexed { index, item ->
            if (index > 0) append(',')
            append("""{"slot":""")
            append(item.slot)
            append(""","count":""")
            append(item.count)
            append(""","source":""")
            append(quoteOrNull(item.source))
            append(""","nbt_b64":"""")
            append(item.nbt)
            append(""""}""")
        }
        append("""],"captured_at":"""")
        append(escape(capturedAt))
        append(""""}""")
    }

    fun selectionCleared(): String = """{"type":"selection_cleared"}"""

    /**
     * A completed trade, as the server announced it in chat.
     *
     * Item names rather than NBT, because that is all chat carries. The app
     * matches them against what it was already pricing.
     */
    fun tradeCompleted(
        counterparty: String?,
        received: List<Pair<Int, String>>,
        given: List<Pair<Int, String>>,
        coinsDelta: Long,
        capturedAt: String,
    ): String = buildString {
        append("""{"type":"trade_completed","counterparty":""")
        append(quoteOrNull(counterparty))
        append(""","items_received":""")
        appendItems(received)
        append(""","items_given":""")
        appendItems(given)
        append(""","coins_delta":""")
        append(coinsDelta)
        append(""","captured_at":"""")
        append(escape(capturedAt))
        append(""""}""")
    }

    private fun StringBuilder.appendItems(items: List<Pair<Int, String>>) {
        append('[')
        items.forEachIndexed { index, (count, name) ->
            if (index > 0) append(',')
            append("""{"count":""")
            append(count)
            append(""","name":"""")
            append(escape(name))
            append(""""}""")
        }
        append(']')
    }

    private fun quoteOrNull(value: String?): String =
        if (value == null) "null" else "\"${escape(value)}\""

    /**
     * JSON string escaping.
     *
     * Written with explicit character constants rather than escape sequences:
     * the only values that ever reach this are names and timestamps, and
     * spelling the characters out leaves no doubt about which backslash
     * belongs to Kotlin and which to JSON.
     */
    private fun escape(value: String): String = buildString(value.length + 8) {
        for (char in value) {
            when (char) {
                QUOTE -> append(BACKSLASH).append(QUOTE)
                BACKSLASH -> append(BACKSLASH).append(BACKSLASH)
                '\n' -> append(BACKSLASH).append('n')
                '\r' -> append(BACKSLASH).append('r')
                '\t' -> append(BACKSLASH).append('t')
                else ->
                    if (char < ' ') {
                        append(BACKSLASH).append("u%04x".format(char.code))
                    } else {
                        append(char)
                    }
            }
        }
    }

    private const val QUOTE: Char = '\u0022'
    private const val BACKSLASH: Char = '\u005C'
}
