package dev.lowball.mixin;

import net.minecraft.client.gui.screens.inventory.AbstractContainerScreen;
import net.minecraft.world.inventory.Slot;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.gen.Accessor;

/**
 * Read-only access to four layout fields the container screen keeps to itself.
 *
 * <p>This is an {@code @Accessor} mixin and nothing else: it adds no behaviour,
 * intercepts no method, and changes nothing the game does. It exists because
 * Minecraft has already worked out which slot the cursor is over, and
 * recomputing that from mouse coordinates would mean hardcoding the vanilla GUI
 * layout and getting it wrong on the first screen that differs.
 *
 * <p>Nothing here touches inventory <em>handling</em> — no click is sent, moved
 * or synthesised. It reads where things are drawn.
 */
@Mixin(AbstractContainerScreen.class)
public interface ContainerScreenAccessor {

    /** The slot under the cursor, or null when the cursor is not over one. */
    @Accessor("hoveredSlot")
    Slot lowball$hoveredSlot();

    /** Left edge of the container window, in screen coordinates. */
    @Accessor("leftPos")
    int lowball$leftPos();

    /** Top edge of the container window, in screen coordinates. */
    @Accessor("topPos")
    int lowball$topPos();

    /**
     * Width of the container window.
     *
     * <p>The overlay panel is placed beside the window rather than at the
     * screen edge, because widgets are drawn before slot contents and anything
     * overlapping the window would end up underneath the items in it.
     */
    @Accessor("imageWidth")
    int lowball$imageWidth();
}
