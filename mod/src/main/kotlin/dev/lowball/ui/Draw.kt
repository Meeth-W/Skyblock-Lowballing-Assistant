package dev.lowball.ui

import net.minecraft.client.gui.GuiGraphicsExtractor

/**
 * The three drawing primitives the whole overlay is built from.
 *
 * Deliberately the same three the desktop app allows itself: a background
 * value shift, a 1px hairline, and 2px of space. No gradients, no shadows, no
 * textures. Nine-slice sprites were the alternative and they are the reason
 * most overlays stop matching their host after a version bump -- vanilla
 * retextures its widgets and the mod inherits a look it never chose.
 * Rectangles do not drift.
 */
object Draw {

    /**
     * A bordered rectangle with its four corner pixels left out.
     *
     * The app draws 4px corner radii. At 1x GUI scale a Minecraft pixel is
     * roughly four of the app's, so one omitted corner pixel is the same
     * gesture at this size -- and it is the only kind of rounding that stays
     * crisp when the user's GUI scale doubles it.
     */
    fun panel(
        graphics: GuiGraphicsExtractor,
        x: Int,
        y: Int,
        width: Int,
        height: Int,
        fill: Int,
        border: Int,
    ) {
        if (width < 2 || height < 2) return
        val right = x + width
        val bottom = y + height
        if (fill != 0) graphics.fill(x + 1, y + 1, right - 1, bottom - 1, fill)
        if (border == 0) return
        graphics.fill(x + 1, y, right - 1, y + 1, border)
        graphics.fill(x + 1, bottom - 1, right - 1, bottom, border)
        graphics.fill(x, y + 1, x + 1, bottom - 1, border)
        graphics.fill(right - 1, y + 1, right, bottom - 1, border)
    }

    /** The app's one separator device. */
    fun hairline(graphics: GuiGraphicsExtractor, x: Int, y: Int, width: Int, colour: Int) {
        graphics.fill(x, y, x + width, y + 1, colour)
    }

    /** A 1px outline with nothing inside it, used to mark a slot. */
    fun outline(
        graphics: GuiGraphicsExtractor,
        x: Int,
        y: Int,
        width: Int,
        height: Int,
        colour: Int,
    ) {
        graphics.fill(x, y, x + width, y + 1, colour)
        graphics.fill(x, y + height - 1, x + width, y + height, colour)
        graphics.fill(x, y + 1, x + 1, y + height - 1, colour)
        graphics.fill(x + width - 1, y + 1, x + width, y + height - 1, colour)
    }
}
