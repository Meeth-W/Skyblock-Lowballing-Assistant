package dev.lowball.ui

/**
 * The desktop app's palette, as ARGB ints.
 *
 * These are the same tokens as `app/lowball/ui/theme.py`, in the same order and
 * under the same names. Two surfaces have to look like one product, and the
 * cheapest way to keep them that way is to make the correspondence literal
 * rather than approximate: when a token moves there, it moves here.
 *
 * The app's rule holds in game too -- the interface has no colour of its own.
 * Structure is a one-step background shift and a 1px hairline; the only
 * saturated pixels are the connection dot, and it is saturated because it is
 * the one thing here that means something.
 */
object Palette {

    // ---- surfaces ----------------------------------------------------------

    /** #09090B. The panel body, at the alpha below. */
    const val CANVAS: Int = 0xFF09090B.toInt()

    /**
     * The panel over the world.
     *
     * Not fully opaque: a container screen is already a dark scrim over the
     * game, and an opaque black rectangle on top of it reads as a hole rather
     * than as a surface.
     */
    const val PANEL: Int = 0xF209090B.toInt()

    const val SURFACE: Int = 0xFF111113.toInt()
    const val SURFACE_HIGH: Int = 0xFF1A1A1E.toInt()
    const val SURFACE_RAISED: Int = 0xFF232329.toInt()

    const val HAIRLINE: Int = 0xFF27272A.toInt()
    const val HAIRLINE_STRONG: Int = 0xFF3F3F46.toInt()

    // ---- ink ---------------------------------------------------------------

    const val INK: Int = 0xFFFAFAFA.toInt()
    const val INK_DIM: Int = 0xFFA1A1AA.toInt()
    const val INK_FAINT: Int = 0xFF71717A.toInt()

    /** The one interactive accent, and it is simply light. */
    const val ACCENT: Int = 0xFFFAFAFA.toInt()
    const val ACCENT_MUTED: Int = 0xFF52525B.toInt()

    // ---- meaning -----------------------------------------------------------

    const val GAIN: Int = 0xFF4ADE80.toInt()
    const val LOSS: Int = 0xFFF87171.toInt()
    const val WARN: Int = 0xFFFBBF24.toInt()

    // ---- slot marking ------------------------------------------------------

    /** A picked slot: a wash of accent, so the item under it stays readable. */
    const val PICKED_FILL: Int = 0x38FAFAFA
    const val PICKED_EDGE: Int = 0xFFFAFAFA.toInt()

    /** The slot under the cursor while the tool is armed. */
    const val ARMED_HOVER_EDGE: Int = 0x66FAFAFA

    /** Scrim behind the pick-order number, so it reads over any item. */
    const val ORDINAL_SCRIM: Int = 0xCC09090B.toInt()
}
