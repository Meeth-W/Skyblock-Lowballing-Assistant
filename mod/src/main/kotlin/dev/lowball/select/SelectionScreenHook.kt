package dev.lowball.select

import dev.lowball.capture.Messages
import dev.lowball.capture.NbtSerializer
import dev.lowball.mixin.ContainerScreenAccessor
import java.time.Instant
import java.util.UUID
import net.fabricmc.fabric.api.client.screen.v1.ScreenEvents
import net.fabricmc.fabric.api.client.screen.v1.ScreenMouseEvents
import net.fabricmc.fabric.api.client.screen.v1.Screens
import net.minecraft.client.gui.GuiGraphicsExtractor
import net.minecraft.client.gui.components.Button
import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen
import net.minecraft.network.chat.Component
import org.slf4j.LoggerFactory

/**
 * The select tool.
 *
 * Every container screen -- your inventory, a chest, the trade window -- gets
 * three buttons: arm the tool, send what is picked, clear it.
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
class SelectionScreenHook(private val send: (String) -> Unit) {

    private val log = LoggerFactory.getLogger("lowball")

    fun register() {
        ScreenEvents.AFTER_INIT.register { _, screen, width, _ ->
            if (screen !is AbstractContainerScreen<*>) return@register
            attach(screen, width)
        }
    }

    private fun attach(screen: AbstractContainerScreen<*>, width: Int) {
        val screenId = UUID.randomUUID().toString()
        val title = screen.title.string
        val x = width - BUTTON_WIDTH - MARGIN

        lateinit var selectButton: Button
        lateinit var sendButton: Button

        fun refresh() {
            selectButton.message = selectLabel()
            sendButton.message = sendLabel()
            sendButton.active = !Selection.isEmpty
        }

        selectButton = Button.builder(selectLabel()) {
            Selection.toggleArmed()
            refresh()
        }.bounds(x, MARGIN, BUTTON_WIDTH, BUTTON_HEIGHT).build()

        sendButton = Button.builder(sendLabel()) {
            sendSelection()
            refresh()
        }.bounds(x, MARGIN + ROW, BUTTON_WIDTH, BUTTON_HEIGHT).build()

        val clearButton = Button.builder(Component.literal("Clear")) {
            Selection.clear()
            send(Messages.selectionCleared())
            refresh()
        }.bounds(x, MARGIN + ROW * 2, BUTTON_WIDTH, BUTTON_HEIGHT).build()

        sendButton.active = !Selection.isEmpty

        val widgets = Screens.getWidgets(screen)
        widgets.add(selectButton)
        widgets.add(sendButton)
        widgets.add(clearButton)

        ScreenMouseEvents.allowMouseClick(screen).register { _, _ ->
            onSlotClick(screen, screenId, title, ::refresh)
        }
        // afterExtract, not afterForeground: the older screen-api that 26.1.2
        // ships has no afterForeground, and this one renders in absolute
        // screen space on both, which is what the offsets below assume.
        ScreenEvents.afterExtract(screen).register { _, graphics, _, _, _ ->
            drawSelected(screen, screenId, graphics)
        }
    }

    private fun selectLabel(): Component =
        Component.literal(if (Selection.armed) "Selecting..." else "Select items")

    private fun sendLabel(): Component =
        Component.literal("Send (${Selection.size})")

    /**
     * Handle a click while the tool is armed.
     *
     * Returns false to cancel, which is what stops the click reaching the game.
     * Clicks that are not over a slot -- the buttons, the background -- are
     * allowed through untouched, so the screen keeps working normally.
     */
    private fun onSlotClick(
        screen: AbstractContainerScreen<*>,
        screenId: String,
        title: String,
        refresh: () -> Unit,
    ): Boolean {
        if (!Selection.armed) return true
        val slot = (screen as ContainerScreenAccessor).`lowball$hoveredSlot`() ?: return true

        val stack = slot.item
        if (stack.isEmpty) {
            // Nothing to pick, but still swallow the click so armed mode can
            // never move an item.
            return false
        }
        val encoded = NbtSerializer.encode(stack)
        if (encoded == null) {
            log.warn("Lowball: could not read slot {} ({})", slot.index, stack.item)
        }
        Selection.toggle(screenId, slot.index, stack, encoded, title)
        refresh()
        return false
    }

    private fun sendSelection() {
        val items = Selection.snapshot()
        if (items.isEmpty()) {
            send(Messages.selectionCleared())
            return
        }
        send(Messages.itemsSelected(items, Instant.now().toString()))
        log.info("Lowball: sent {} item(s) to the desktop app", items.size)
    }

    /**
     * Outline the slots that are currently picked.
     *
     * Slot coordinates are relative to the container window, so they are
     * offset by its origin to land in the absolute screen space this draws in.
     */
    private fun drawSelected(
        screen: AbstractContainerScreen<*>,
        screenId: String,
        graphics: GuiGraphicsExtractor,
    ) {
        if (Selection.isEmpty) return
        val accessor = screen as ContainerScreenAccessor
        val left = accessor.`lowball$leftPos`()
        val top = accessor.`lowball$topPos`()

        for (slot in screen.menu.slots) {
            if (!Selection.isSelected(screenId, slot.index)) continue
            val x = left + slot.x
            val y = top + slot.y
            graphics.fill(x, y, x + SLOT, y + SLOT, SELECTED_FILL)
            graphics.outline(x, y, SLOT, SLOT, SELECTED_EDGE)
        }
    }

    private companion object {
        const val BUTTON_WIDTH = 96
        const val BUTTON_HEIGHT = 20
        const val MARGIN = 6
        const val ROW = 24
        const val SLOT = 16

        /** Brass, matching the app's selection accent. */
        const val SELECTED_FILL = 0x55C9974A.toInt()
        const val SELECTED_EDGE = 0xFFC9974A.toInt()
    }
}
