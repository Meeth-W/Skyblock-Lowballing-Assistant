package dev.lowball.capture

import java.io.ByteArrayOutputStream
import java.util.Base64
import net.minecraft.core.component.DataComponents
import net.minecraft.core.registries.BuiltInRegistries
import net.minecraft.nbt.CompoundTag
import net.minecraft.nbt.ListTag
import net.minecraft.nbt.NbtIo
import net.minecraft.nbt.StringTag
import net.minecraft.world.item.ItemStack

/**
 * Serialising an item stack the way the app expects to read it.
 *
 * The payload is built explicitly from the three things the app reads --
 * `custom_data`, the display name and the lore -- rather than by asking
 * `ItemStack.CODEC` to encode the whole stack.
 *
 * That is a deliberate reversal. The first build used the codec, and every
 * item reached the app unreadable. The codec route fails by returning an empty
 * result rather than throwing, so nothing on either side had anything to
 * report; the app simply showed nothing. Worse, it cannot be tested without a
 * running client, so the failure was only ever going to surface in game.
 *
 * [buildPayload] has no Minecraft state in it beyond the tags handed to it, so
 * it is exercised against the app's real parser in the test suite. One proven
 * path is worth more than two where one of them cannot be checked.
 *
 * Nothing is lost by the swap: `custom_data` carries every SkyBlock attribute
 * there is -- id, reforge, stars, enchantments, gems, pet info, the lot.
 *
 * Output is gzip then base64, matching the encoding the Hypixel API uses.
 */
object NbtSerializer {

    /** Encode one stack, or null for an empty slot or a stack with no data. */
    fun encode(stack: ItemStack): String? {
        if (stack.isEmpty) return null

        val custom = stack.get(DataComponents.CUSTOM_DATA)?.copyTag()
        val name = stack.get(DataComponents.CUSTOM_NAME) ?: stack.get(DataComponents.ITEM_NAME)
        val lore = stack.get(DataComponents.LORE)
        if (custom == null && name == null && lore == null) return null

        return encodeTag(
            buildPayload(
                itemId = BuiltInRegistries.ITEM.getKey(stack.item).toString(),
                count = stack.count,
                customData = custom,
                displayName = name?.string,
                lore = lore?.lines()?.map { it.string } ?: emptyList(),
            )
        )
    }

    /**
     * Assemble the component-layout compound the app parses.
     *
     * `custom_data` is copied through exactly as the server sent it. On a
     * modern client Hypixel writes the SkyBlock attributes straight into it,
     * with no `ExtraAttributes` wrapper -- that wrapper belonged to the old
     * 1.8 `tag` compound. Re-wrapping here would be inventing a shape the
     * server does not use.
     */
    fun buildPayload(
        itemId: String,
        count: Int,
        customData: CompoundTag?,
        displayName: String?,
        lore: List<String>,
    ): CompoundTag {
        val components = CompoundTag()
        if (customData != null) components.put("minecraft:custom_data", customData)
        if (displayName != null) components.putString("minecraft:custom_name", displayName)
        if (lore.isNotEmpty()) {
            val lines = ListTag()
            for (line in lore) lines.add(StringTag.valueOf(line))
            components.put("minecraft:lore", lines)
        }
        return CompoundTag().apply {
            putString("id", itemId)
            putInt("count", count)
            put("components", components)
        }
    }

    /** gzip + base64. Exposed so a payload can be tested end to end. */
    fun encodeTag(tag: CompoundTag): String? {
        val bytes = ByteArrayOutputStream()
        return try {
            NbtIo.writeCompressed(tag, bytes)
            Base64.getEncoder().encodeToString(bytes.toByteArray())
        } catch (_: Exception) {
            null
        }
    }
}
