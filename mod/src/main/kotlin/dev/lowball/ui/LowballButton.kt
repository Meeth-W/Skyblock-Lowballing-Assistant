package dev.lowball.ui

import net.minecraft.client.Minecraft
import net.minecraft.client.gui.GuiGraphicsExtractor
import net.minecraft.client.gui.components.AbstractWidget
import net.minecraft.client.gui.narration.NarrationElementOutput
import net.minecraft.client.input.MouseButtonEvent
import net.minecraft.network.chat.Component

/**
 * A button that looks like the desktop app rather than like Minecraft.
 *
 * It extends [AbstractWidget] rather than `Button` so that nothing of the
 * vanilla appearance is inherited: `AbstractButton` draws its sprite in a
 * `final` method, so a subclass of it can restyle the label and nothing else.
 * Everything vanilla actually provides -- hit testing, the click sound, focus
 * traversal, narration, the tooltip holder -- comes from [AbstractWidget] and
 * is kept.
 *
 * The three styles are the three the app's stylesheet defines, with the same
 * names and the same state transitions: [Style.DEFAULT] is `QPushButton`,
 * [Style.PRIMARY] is `QPushButton#primary`, [Style.GHOST] is
 * `QPushButton#ghost`.
 */
class LowballButton(
    x: Int,
    y: Int,
    width: Int,
    height: Int,
    label: Component,
    private val style: Style,
    private val onPress: () -> Unit,
) : AbstractWidget(x, y, width, height, label) {

    enum class Style { DEFAULT, PRIMARY, GHOST }

    /**
     * On, for a button that is a switch rather than an act.
     *
     * Select items is the only one. A toggled button is not a primary button:
     * primary says "this is the thing to do next", and an armed select tool is
     * a mode the user is already in.
     */
    var toggled: Boolean = false

    override fun onClick(event: MouseButtonEvent, doubled: Boolean) {
        onPress()
    }

    override fun extractWidgetRenderState(
        graphics: GuiGraphicsExtractor,
        mouseX: Int,
        mouseY: Int,
        partialTick: Float,
    ) {
        val hovered = isHoveredOrFocused()
        val enabled = active

        val fill: Int
        val border: Int
        val ink: Int

        when {
            !enabled && style == Style.PRIMARY -> {
                fill = Palette.ACCENT_MUTED
                border = Palette.ACCENT_MUTED
                ink = Palette.CANVAS
            }
            !enabled && style == Style.GHOST -> {
                // A ghost that grows a border when it is turned off reads as
                // heavier than the same button working, which is backwards. It
                // recedes instead.
                fill = 0
                border = 0
                ink = Palette.INK_FAINT
            }
            !enabled -> {
                fill = Palette.SURFACE
                border = Palette.HAIRLINE
                ink = Palette.INK_FAINT
            }
            style == Style.PRIMARY -> {
                fill = if (hovered) WHITE else Palette.ACCENT
                border = fill
                ink = Palette.CANVAS
            }
            style == Style.GHOST -> {
                fill = if (hovered) Palette.SURFACE_HIGH else 0
                border = 0
                ink = if (hovered) Palette.INK else Palette.INK_DIM
            }
            toggled -> {
                fill = Palette.SURFACE_RAISED
                border = Palette.ACCENT
                ink = Palette.INK
            }
            hovered -> {
                fill = Palette.SURFACE_RAISED
                border = Palette.HAIRLINE_STRONG
                ink = Palette.INK
            }
            else -> {
                fill = Palette.SURFACE_HIGH
                border = Palette.HAIRLINE
                ink = Palette.INK
            }
        }

        Draw.panel(graphics, x, y, width, height, fill, border)

        val font = Minecraft.getInstance().font
        graphics.centeredText(
            font,
            message,
            x + width / 2,
            y + (height - FONT_HEIGHT) / 2,
            ink,
        )
    }

    override fun updateWidgetNarration(output: NarrationElementOutput) {
        defaultButtonNarrationText(output)
    }

    private companion object {
        const val WHITE: Int = 0xFFFFFFFF.toInt()

        /** Minecraft's glyph box, which is 8 tall inside a 9px line. */
        const val FONT_HEIGHT: Int = 8
    }
}
