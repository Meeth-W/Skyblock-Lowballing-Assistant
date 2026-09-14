package dev.lowball.chat

import dev.lowball.capture.Messages
import java.time.Instant

/**
 * Reading completed trades out of the chat log.
 *
 * Hypixel already announces exactly what changed hands:
 *
 * ```
 * Trade completed with [MVP+] Thxnndrr!
 *  + 1x Ancient Warden Helmet
 *  - 390M coins
 * ```
 *
 * That is better ground truth than the inventory diff this replaces. The diff
 * had to guess at timing, could not tell a trade from any other inventory
 * change in the same tick, and got the price from scraping the sidebar. The
 * server states the settled figure outright.
 *
 * What it does not give is item NBT, only display names. So this reports names
 * and the app matches them against the items it was already pricing. That is
 * the right split: the app knows what it quoted, chat knows what was agreed.
 *
 * Purely a reader. It observes messages the client has already received and
 * sends nothing, to the server or to chat.
 */
class TradeChatWatcher(private val send: (String) -> Unit) {

    private var counterparty: String? = null
    private val received = ArrayList<TradedItem>()
    private val given = ArrayList<TradedItem>()
    private var coinsDelta = 0L
    private var flushCountdown = -1

    /** Feed one received chat line. Safe to call with anything. */
    fun onMessage(raw: String) {
        // A trade block may arrive as one component with newlines or as one
        // message per line; handling both costs nothing and guessing wrong
        // would lose the trade.
        for (line in raw.split('\n')) {
            handleLine(strip(line))
        }
    }

    private fun handleLine(line: String) {
        val header = HEADER.find(line)
        if (header != null) {
            flush()
            counterparty = header.groupValues[1]
            flushCountdown = FLUSH_TICKS
            return
        }
        if (counterparty == null) return

        val entry = ENTRY.find(line) ?: return
        val sign = if (entry.groupValues[1] == "+") 1 else -1
        val count = entry.groupValues[2].toIntOrNull() ?: 1
        val body = entry.groupValues[3].trim()

        val coins = COINS.find(body)
        if (coins != null) {
            coinsDelta += sign * parseAmount(coins.groupValues[1])
        } else {
            val item = TradedItem(count, body)
            if (sign > 0) received.add(item) else given.add(item)
        }
        flushCountdown = FLUSH_TICKS
    }

    /**
     * Driven from the client tick.
     *
     * The lines arrive over a few ticks, so the block is held briefly and sent
     * once it stops growing rather than one message per line.
     */
    fun tick() {
        if (flushCountdown < 0) return
        flushCountdown -= 1
        if (flushCountdown <= 0) flush()
    }

    private fun flush() {
        val who = counterparty
        counterparty = null
        flushCountdown = -1
        if (who == null) return

        val hadContent = received.isNotEmpty() || given.isNotEmpty() || coinsDelta != 0L
        if (hadContent) {
            send(
                Messages.tradeCompleted(
                    who,
                    received.map { it.count to it.name },
                    given.map { it.count to it.name },
                    coinsDelta,
                    Instant.now().toString(),
                )
            )
        }
        received.clear()
        given.clear()
        coinsDelta = 0L
    }

    private fun strip(text: String): String = FORMAT_CODE.replace(text, "")

    private data class TradedItem(val count: Int, val name: String)

    private companion object {
        /** `Trade completed with [MVP+] Thxnndrr!` -- the rank is optional. */
        val HEADER = Regex("""Trade completed with\s+(?:\[[^\]]*\]\s*)?(\w{2,16})""")

        /** ` + 1x Ancient Warden Helmet` or ` - 390M coins`; the count is optional. */
        val ENTRY = Regex("""^\s*([+\u2212-])\s*(?:(\d+)\s*x\s+)?(.+?)\s*$""")

        val COINS = Regex("""^([\d.,]+\s*[kKmMbBtT]?)\s*coins?$""", RegexOption.IGNORE_CASE)

        val FORMAT_CODE = Regex("[\u00a7&][0-9a-fk-orA-FK-OR]")

        /** Ticks of quiet before a trade block is considered finished. */
        const val FLUSH_TICKS = 10

        fun parseAmount(text: String): Long {
            val cleaned = text.replace(",", "").replace(" ", "").trim()
            val unit = when (cleaned.lastOrNull()?.lowercaseChar()) {
                'k' -> 1_000L
                'm' -> 1_000_000L
                'b' -> 1_000_000_000L
                't' -> 1_000_000_000_000L
                else -> 1L
            }
            val digits = if (unit == 1L) cleaned else cleaned.dropLast(1)
            val value = digits.toDoubleOrNull() ?: return 0L
            return (value * unit).toLong()
        }
    }
}
