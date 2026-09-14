import dev.lowball.capture.Messages;
import dev.lowball.capture.NbtSerializer;
import dev.lowball.chat.TradeChatWatcher;
import dev.lowball.select.SelectedItem;
import net.minecraft.nbt.CompoundTag;
import java.util.List;

/**
 * Captures the mod's real wire output into a fixture the Python tests decode.
 *
 * Three things are exercised here that cannot be checked from Python alone:
 * the hand-rolled JSON escaping; the chat parser, driven with the exact text
 * Hypixel prints when a trade completes; and the item payload builder, which
 * is the fallback used whenever ItemStack.CODEC comes back without SkyBlock's
 * data in it.
 *
 *   javac -encoding UTF-8 -cp <mod jar>;<mc jar>;<libs> -d out ModMessageProbe.java
 *   java -Dstdout.encoding=UTF-8 -cp out;... ModMessageProbe > mod_messages.jsonl
 */
public class ModMessageProbe {

    public static void main(String[] args) {
        Messages m = Messages.INSTANCE;

        // A player name with characters that must be escaped.
        System.out.println(m.hello("0.2.0", "26.1.2", "uuid-1", "Notch\"\\x"));

        // A real item payload, built the way the fallback path builds it.
        System.out.println(m.itemsSelected(List.of(
            new SelectedItem("s#13", 13, hyperion(), "Large Chest", 1),
            new SelectedItem("s#27", 27, book(), "Large Chest", 16)
        ), "2026-09-14T10:30:00Z"));

        System.out.println(m.selectionCleared());

        TradeChatWatcher watcher = new TradeChatWatcher(line -> {
            System.out.println(line);
            return kotlin.Unit.INSTANCE;
        });
        feed(watcher,
            "Trade completed with [MVP+] Thxnndrr!",
            " + 1x Ancient Warden Helmet",
            " + 1x Ancient Burning Crimson Chestplate",
            " + 1x Ancient Burning Crimson Leggings",
            " + 1x Ancient Burning Crimson Boots",
            " - 390M coins");
        feed(watcher,
            "Trade completed with [MVP+] koreacantplayMC!",
            " - 1.6B coins",
            " + 1x Heroic Hyperion ✪✪✪✪✪");
        feed(watcher,
            "Trade completed with Alice!",
            " - 1x Terminator",
            " + 250,000,000 coins");
    }

    /** A starred, reforged Hyperion through the fallback payload builder. */
    private static String hyperion() {
        CompoundTag extra = new CompoundTag();
        extra.putString("id", "HYPERION");
        extra.putString("uuid", "6e1b0a3c-9f2d-4a11-b7e8-a1b2c3d4e5f6");
        extra.putString("modifier", "heroic");
        extra.putInt("upgrade_level", 5);
        extra.putInt("rarity_upgrades", 1);
        CompoundTag enchants = new CompoundTag();
        enchants.putInt("ultimate_wise", 5);
        enchants.putInt("sharpness", 7);
        extra.put("enchantments", enchants);

        CompoundTag custom = new CompoundTag();
        custom.put("ExtraAttributes", extra);

        CompoundTag payload = NbtSerializer.INSTANCE.buildPayload(
            "minecraft:diamond_sword", 1, custom,
            "§dHeroic Hyperion §6✪✪✪✪✪",
            List.of("§d§lMYTHIC DUNGEON SWORD"));
        return NbtSerializer.INSTANCE.encodeTag(payload);
    }

    /** A stackable, which has no item uuid to be tracked by. */
    private static String book() {
        CompoundTag extra = new CompoundTag();
        extra.putString("id", "ENCHANTED_BOOK");
        CompoundTag enchants = new CompoundTag();
        enchants.putInt("ultimate_wise", 5);
        extra.put("enchantments", enchants);

        CompoundTag custom = new CompoundTag();
        custom.put("ExtraAttributes", extra);

        CompoundTag payload = NbtSerializer.INSTANCE.buildPayload(
            "minecraft:enchanted_book", 16, custom,
            "§aEnchanted Book",
            List.of("§9Ultimate Wise V", "§6§lLEGENDARY"));
        return NbtSerializer.INSTANCE.encodeTag(payload);
    }

    private static void feed(TradeChatWatcher watcher, String... lines) {
        for (String line : lines) {
            watcher.onMessage(line);
        }
        for (int tick = 0; tick < 20; tick++) {
            watcher.tick();
        }
    }
}
