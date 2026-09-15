package dev.lowball.ui

import net.minecraft.client.Minecraft
import net.minecraft.client.gui.GuiGraphicsExtractor
import net.minecraft.client.gui.components.AbstractWidget
import net.minecraft.client.gui.components.Tooltip
import net.minecraft.client.gui.narration.NarrationElementOutput
import net.minecraft.client.input.MouseButtonEvent
import net.minecraft.network.chat.Component

/** What the uplink is doing, as far as the panel needs to know. */
enum class LinkState(val labelKey: String, val colour: Int) {
    CONNECTED("lowball.status.connected", Palette.GAIN),
    CONNECTING("lowball.status.connecting", Palette.WARN),
    OFFLINE("lowball.status.offline", Palette.LOSS),
}

/** Everything the panel has to be told, gathered in one place. */
data class PanelState(
    val armed: Boolean,
    val picked: Int,
    val link: LinkState,
)

/**
 * The mod's whole interface: one panel beside the container window.
 *
 * Anchored to the container rather than to the screen edge. Widgets are drawn
 * before slot contents, so a panel that overlapped the window would end up
 * underneath the items in it; sitting beside the window means it cannot, at
 * any GUI scale. It also puts the controls where the user is already looking.
 *
 * The panel owns its geometry and its three buttons. [refresh] is the only way
 * its contents change, so there is exactly one place where the labels, the
 * enabled states and the status line can disagree with each other -- and they
 * are all written there together.
 */
class OverlayPanel(
    onToggleArm: () -> Unit,
    onSend: () -> Unit,
    onClear: () -> Unit,
) {

    private var state = PanelState(armed = false, picked = 0, link = LinkState.OFFLINE)

    private var flashMessage: Component? = null
    private var flashColour: Int = Palette.INK_DIM
    private var flashUntil: Long = 0L

    var x: Int = 0
        private set
    var y: Int = 0
        private set

    private val backdrop = Backdrop()

    private val selectButton = LowballButton(
        0, 0, WIDTH - PAD * 2, BUTTON_HEIGHT,
        Component.translatable("lowball.button.select"),
        LowballButton.Style.DEFAULT,
        onToggleArm,
    ).apply {
        setTooltip(Tooltip.create(Component.translatable("lowball.tooltip.select")))
    }

    private val sendButton = LowballButton(
        0, 0, WIDTH - PAD * 2, BUTTON_HEIGHT,
        Component.translatable("lowball.button.send.empty"),
        LowballButton.Style.PRIMARY,
        onSend,
    )

    private val clearButton = LowballButton(
        0, 0, WIDTH - PAD * 2, GHOST_HEIGHT,
        Component.translatable("lowball.button.clear"),
        LowballButton.Style.GHOST,
        onClear,
    ).apply {
        setTooltip(Tooltip.create(Component.translatable("lowball.tooltip.clear")))
    }

    /**
     * In render order: the backdrop first, so the buttons sit on it.
     *
     * Screens render their widget list in insertion order, which is the only
     * layering guarantee available without reaching into the render pipeline.
     */
    val widgets: List<AbstractWidget> =
        listOf(backdrop, selectButton, sendButton, clearButton)

    /**
     * Place the panel beside the container window.
     *
     * Right of it by preference, left when the right would run off screen, and
     * pinned to the screen edge only when neither side fits -- which needs a
     * window narrower than the container itself plus twice the panel.
     */
    fun layout(screenWidth: Int, containerLeft: Int, containerTop: Int, containerWidth: Int) {
        val right = containerLeft + containerWidth + GAP
        x = when {
            right + WIDTH + MARGIN <= screenWidth -> right
            containerLeft - WIDTH - GAP >= MARGIN -> containerLeft - WIDTH - GAP
            else -> (screenWidth - WIDTH - MARGIN).coerceAtLeast(MARGIN)
        }
        y = containerTop.coerceAtLeast(MARGIN)

        backdrop.setRectangle(WIDTH, HEIGHT, x, y)
        selectButton.setPosition(x + PAD, y + SELECT_Y)
        sendButton.setPosition(x + PAD, y + SEND_Y)
        clearButton.setPosition(x + PAD, y + CLEAR_Y)
    }

    fun contains(mouseX: Double, mouseY: Double): Boolean =
        mouseX >= x && mouseX < x + WIDTH && mouseY >= y && mouseY < y + HEIGHT

    /**
     * Say something for a moment, on the panel's last line.
     *
     * The alternative was chat, and chat is where a mod that must never be
     * mistaken for one that talks to the server should least of all be writing.
     * It is also the wrong place: the user is looking at the container window,
     * not at the log behind it.
     */
    fun flash(message: Component, colour: Int) {
        flashMessage = message
        flashColour = colour
        flashUntil = System.currentTimeMillis() + FLASH_MS
    }

    /** The one place labels, enabled states and the status line are decided. */
    fun refresh(next: PanelState) {
        state = next

        selectButton.toggled = next.armed
        selectButton.setMessage(
            if (next.armed) {
                Component.translatable("lowball.button.selecting")
            } else {
                Component.translatable("lowball.button.select")
            }
        )

        sendButton.setMessage(
            if (next.picked == 0) {
                Component.translatable("lowball.button.send.empty")
            } else {
                Component.translatable("lowball.button.send", next.picked)
            }
        )
        sendButton.active = next.picked > 0
        sendButton.setTooltip(
            Tooltip.create(
                if (next.link == LinkState.CONNECTED) {
                    Component.translatable("lowball.tooltip.send")
                } else {
                    Component.translatable("lowball.tooltip.send.offline")
                }
            )
        )

        clearButton.active = next.picked > 0
    }

    /** The chrome: the card, its header, its rules and its status line. */
    private inner class Backdrop : AbstractWidget(
        0, 0, WIDTH, HEIGHT, Component.translatable("lowball.panel.title")
    ) {
        init {
            // Decoration, not a control: it takes no click and no focus, so a
            // click that lands between the buttons still reaches the screen.
            active = false
        }

        override fun onClick(event: MouseButtonEvent, doubled: Boolean) = Unit

        override fun updateWidgetNarration(output: NarrationElementOutput) = Unit

        override fun extractWidgetRenderState(
            graphics: GuiGraphicsExtractor,
            mouseX: Int,
            mouseY: Int,
            partialTick: Float,
        ) {
            val font = Minecraft.getInstance().font
            val left = this.x
            val top = this.y
            Draw.panel(graphics, left, top, WIDTH, HEIGHT, Palette.PANEL, Palette.HAIRLINE)

            // Header: a connection dot that means something, and a wordmark
            // that does not. The dot is the only saturated pixel on the panel.
            graphics.fill(
                left + PAD,
                top + PAD + 2,
                left + PAD + DOT,
                top + PAD + 2 + DOT,
                state.link.colour,
            )
            graphics.text(
                font,
                Component.translatable("lowball.panel.title"),
                left + PAD + DOT + PAD,
                top + PAD,
                Palette.INK_FAINT,
            )
            Draw.hairline(
                graphics, left + PAD, top + HEADER_RULE_Y, WIDTH - PAD * 2, Palette.HAIRLINE
            )

            Draw.hairline(
                graphics, left + PAD, top + FOOTER_RULE_Y, WIDTH - PAD * 2, Palette.HAIRLINE
            )
            graphics.text(
                font,
                Component.translatable(state.link.labelKey),
                left + PAD,
                top + STATUS_Y,
                state.link.colour,
            )
            val flash = flashMessage.takeIf { System.currentTimeMillis() < flashUntil }
            when {
                flash != null -> graphics.text(
                    font, flash, left + PAD, top + HINT_Y,
                    flashColour,
                )
                // Said out loud because an armed tool swallows every slot
                // click, including in the player's own inventory. A user who
                // has forgotten it is on would otherwise think the game hung.
                state.armed -> graphics.text(
                    font,
                    Component.translatable("lowball.hint.armed"),
                    left + PAD,
                    top + HINT_Y,
                    Palette.INK_DIM,
                )
            }
        }
    }

    companion object {
        const val WIDTH: Int = 108
        const val HEIGHT: Int = 99

        private const val PAD: Int = 4
        private const val GAP: Int = 4
        private const val MARGIN: Int = 4
        private const val DOT: Int = 3
        private const val BUTTON_HEIGHT: Int = 16
        private const val GHOST_HEIGHT: Int = 14

        private const val HEADER_RULE_Y: Int = 15
        private const val SELECT_Y: Int = 19
        private const val SEND_Y: Int = 37
        private const val CLEAR_Y: Int = 55
        private const val FOOTER_RULE_Y: Int = 73
        private const val STATUS_Y: Int = 77
        private const val HINT_Y: Int = 87

        /** Long enough to read one short line, short enough not to linger. */
        private const val FLASH_MS: Long = 2_500L
    }
}
