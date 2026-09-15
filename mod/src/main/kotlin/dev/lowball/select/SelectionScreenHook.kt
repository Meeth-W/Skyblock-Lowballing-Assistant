package dev.lowball.select

import dev.lowball.capture.Messages
import dev.lowball.capture.NbtSerializer
import dev.lowball.mixin.ContainerScreenAccessor
import dev.lowball.ui.Draw
import dev.lowball.ui.LinkState
import dev.lowball.ui.OverlayPanel
import dev.lowball.ui.Palette
import dev.lowball.ui.PanelState
import java.time.Instant
import net.fabricmc.fabric.api.client.screen.v1.ScreenEvents
import net.fabricmc.fabric.api.client.screen.v1.ScreenMouseEvents
import net.fabricmc.fabric.api.client.screen.v1.Screens
import net.minecraft.client.Minecraft
import net.minecraft.client.gui.GuiGraphicsExtractor
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen
import net.minecraft.network.chat.Component
import net.minecraft.world.inventory.Slot
import org.slf4j.LoggerFactory

/**
 * The select tool.
 *
 * Every container screen -- your inventory, a chest, the trade window -- gets
 * the overlay panel: arm the tool, send what is picked, clear it.
 *
 * Sending is a separate, deliberate act rather than something that happens on
 * every click. Picking items is fiddly and often involves changing your mind;
 * the app should see the set you settled on, once, not every intermediate
 * state of it.
 *
 * **Nothing is sent to the server.** While armed, a click over a slot is
 * cancelled before vanilla sees it, so it causes no in-game action at all --
 * it is swallowed, not redirected. Clicks that are not over a slot pass
 * through, and while disarmed the mod does not touch input.
 */
class SelectionScreenHook(
    private val send: (String) -> Unit,
    private val link: () -> LinkState,
) {

    private val log = LoggerFactory.getLogger("lowball")

    fun register() {
        ScreenEvents.AFTER_INIT.register { _, screen, width, _ ->
            if (screen !is AbstractContainerScreen<*>) return@register
            attach(screen, width)
        }
    }

    private fun attach(screen: AbstractContainerScreen<*>, width: Int) {
        val accessor = screen as ContainerScreenAccessor
        val screenId = identify(screen)
        val title = screen.title.string

        lateinit var panel: OverlayPanel

        fun refresh() {
            panel.refresh(
                PanelState(
                    armed = Selection.armed,
                    picked = Selection.size,
                    link = link(),
                )
            )
        }

        panel = OverlayPanel(
            onToggleArm = {
                Selection.toggleArmed()
                refresh()
            },
            onSend = {
                sendSelection(panel)
                refresh()
            },
            onClear = {
                val had = Selection.size
                Selection.clear()
                send(Messages.selectionCleared())
                panel.flash(
                    Component.translatable("lowball.flash.cleared", had), Palette.INK_DIM
                )
                refresh()
            },
        )

        panel.layout(
            width,
            accessor.`lowball$leftPos`(),
            accessor.`lowball$topPos`(),
            accessor.`lowball$imageWidth`(),
        )
        refresh()
        Screens.getWidgets(screen).addAll(panel.widgets)

        ScreenMouseEvents.allowMouseClick(screen).register { _, event ->
            onSlotClick(screen, screenId, title, panel, event.x(), event.y(), ::refresh)
        }
        // afterExtract, not afterForeground: the older screen-api that 26.1.2
        // ships has no afterForeground, and this one renders in absolute
        // screen space on both, which is what the offsets below assume. It is
        // also the only hook that runs after the slot contents, which is what
        // a mark on top of an item needs.
        ScreenEvents.afterExtract(screen).register { _, graphics, _, _, _ ->
            drawMarks(screen, screenId, graphics)
        }
    }

    /**
     * A name for this screen that survives it being rebuilt.
     *
     * The server's container id plus the title. A screen is reconstructed
     * whenever the window is resized, so a value minted per construction would
     * quietly orphan every item already picked from it: still in the set, no
     * longer drawn as picked, and pickable a second time under a new key.
     *
     * The player's own inventory has container id 0 on every screen that shows
     * it, which is exactly right -- the same slot is the same item.
     */
    private fun identify(screen: AbstractContainerScreen<*>): String =
        "${screen.menu.containerId}:${screen.title.string}"

    /**
     * Handle a click while the tool is armed.
     *
     * Returns false to cancel, which is what stops the click reaching the game.
     * Clicks that are not over a slot -- the panel, the background -- are
     * allowed through untouched, so the screen keeps working normally.
     */
    private fun onSlotClick(
        screen: AbstractContainerScreen<*>,
        screenId: String,
        title: String,
        panel: OverlayPanel,
        mouseX: Double,
        mouseY: Double,
        refresh: () -> Unit,
    ): Boolean {
        if (!Selection.armed) return true
        // The panel can sit over a slot when the window is too narrow for it
        // to sit beside one. Its own clicks have to win, or arming the tool
        // would be a trap with no way out of it.
        if (panel.contains(mouseX, mouseY)) return true
        val slot = (screen as ContainerScreenAccessor).`lowball$hoveredSlot`() ?: return true

        val stack = slot.item
        if (stack.isEmpty) {
            // Nothing to pick, but still swallow the click so armed mode can
            // never move an item.
            return false
        }
        val encoded = NbtSerializer.encode(stack)
        when (Selection.toggle(screenId, slot.index, stack, encoded, title)) {
            Selection.Outcome.ADDED, Selection.Outcome.REMOVED -> Unit
            Selection.Outcome.UNREADABLE -> {
                // Silence here was the old behaviour, and it meant a slot that
                // simply would not pick with nothing said about why.
                log.warn("Lowball: could not read slot {} ({})", slot.index, stack.item)
                panel.flash(Component.translatable("lowball.flash.unreadable"), Palette.LOSS)
            }
            Selection.Outcome.FULL ->
                panel.flash(
                    Component.translatable("lowball.flash.full", Selection.MAX_ITEMS),
                    Palette.WARN,
                )
        }
        refresh()
        return false
    }

    private fun sendSelection(panel: OverlayPanel) {
        val items = Selection.snapshot()
        if (items.isEmpty()) {
            send(Messages.selectionCleared())
            return
        }
        send(Messages.itemsSelected(items, Instant.now().toString()))
        log.info("Lowball: sent {} item(s) to the desktop app", items.size)
        panel.flash(
            Component.translatable("lowball.flash.sent", items.size),
            if (link() == LinkState.CONNECTED) Palette.GAIN else Palette.WARN,
        )
    }

    /**
     * Mark the slots that matter: what is picked, and what a click would pick.
     *
     * Slot coordinates are relative to the container window, so they are
     * offset by its origin to land in the absolute screen space this draws in.
     */
    private fun drawMarks(
        screen: AbstractContainerScreen<*>,
        screenId: String,
        graphics: GuiGraphicsExtractor,
    ) {
        val accessor = screen as ContainerScreenAccessor
        val left = accessor.`lowball$leftPos`()
        val top = accessor.`lowball$topPos`()
        val hovered: Slot? = accessor.`lowball$hoveredSlot`()

        if (Selection.armed && hovered != null && !Selection.isSelected(screenId, hovered.index)) {
            // What a click is about to do, shown before it does it. The tool
            // changes what every slot click means, so the slot has to say so.
            Draw.outline(
                graphics, left + hovered.x, top + hovered.y, SLOT, SLOT,
                Palette.ARMED_HOVER_EDGE,
            )
        }

        val ordinals = Selection.ordinalsFor(screenId)
        if (ordinals.isEmpty()) return
        val font = Minecraft.getInstance().font
        for (slot in screen.menu.slots) {
            val ordinal = ordinals[slot.index] ?: continue
            val x = left + slot.x
            val y = top + slot.y
            graphics.fill(x, y, x + SLOT, y + SLOT, Palette.PICKED_FILL)
            Draw.outline(graphics, x, y, SLOT, SLOT, Palette.PICKED_EDGE)

            // The pick order, top-left, over a scrim so it reads on any item.
            // The app lists items in this order; without it, matching a row on
            // screen to an item in the window means counting clicks backwards.
            val label = ordinal.toString()
            val labelWidth = font.width(label)
            graphics.fill(x, y, x + labelWidth + 2, y + 9, Palette.ORDINAL_SCRIM)
            graphics.text(font, label, x + 1, y + 1, Palette.INK)
        }
    }

    private companion object {
        const val SLOT = 16
    }
}
