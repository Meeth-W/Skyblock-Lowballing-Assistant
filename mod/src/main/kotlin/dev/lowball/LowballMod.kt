package dev.lowball

import dev.lowball.capture.Messages
import dev.lowball.chat.TradeChatWatcher
import dev.lowball.net.UplinkClient
import dev.lowball.select.SelectionScreenHook
import net.fabricmc.api.ClientModInitializer
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents
import net.fabricmc.fabric.api.client.message.v1.ClientReceiveMessageEvents
import net.minecraft.client.Minecraft
import org.slf4j.LoggerFactory

/**
 * Lowball Uplink.
 *
 * The complete list of what this mod does:
 *
 *  1. put Select / Send / Clear buttons on container screens;
 *  2. while the tool is armed, treat a click on a slot as picking that item
 *     for pricing;
 *  3. send the picked items to a desktop app on loopback when Send is pressed;
 *  4. watch chat for the server's own trade-completed announcement, and
 *     forward what it says changed hands;
 *  5. keep that outbound WebSocket open.
 *
 * Nothing else. It sends **zero** packets to the server, runs no commands,
 * writes no chat, and binds no key at all. Hypixel's rules prohibit external
 * software automating a player action, and macros -- one input producing one
 * in-game action -- are banned separately.
 *
 * The select tool is the opposite of a macro: while armed, a click over a slot
 * is swallowed, so it causes *no* in-game action where it normally would cause
 * one. The mod renders a button and reads what the client already has. The
 * desktop app has no channel back into the game; there is no receive path here
 * to add one to.
 */
object LowballMod : ClientModInitializer {

    private val log = LoggerFactory.getLogger("lowball")

    private lateinit var uplink: UplinkClient
    private lateinit var selection: SelectionScreenHook
    private lateinit var chat: TradeChatWatcher

    private var greeted = false

    override fun onInitializeClient() {
        uplink = UplinkClient(Config.HOST, Config.PORT)
        uplink.onConnected = {
            greeted = false
            log.info("Lowball: connected to the desktop app on {}:{}", Config.HOST, Config.PORT)
        }
        uplink.onDisconnected = {
            greeted = false
            log.info("Lowball: desktop app went away, will keep retrying")
        }
        uplink.start()

        selection = SelectionScreenHook(uplink::send)
        selection.register()

        chat = TradeChatWatcher(uplink::send)
        // Hypixel announces trades as system messages rather than player chat.
        ClientReceiveMessageEvents.GAME.register { message, overlay ->
            if (!overlay) chat.onMessage(message.string)
        }
        ClientReceiveMessageEvents.CHAT.register { message, _, _, _, _ ->
            chat.onMessage(message.string)
        }

        ClientTickEvents.END_CLIENT_TICK.register(::onClientTick)
        log.info("Lowball uplink ready, read-only, sending to ws://{}:{}", Config.HOST, Config.PORT)
    }

    private fun onClientTick(client: Minecraft) {
        // A trade block arrives over several ticks; this is what closes it off.
        chat.tick()

        val player = client.player
        if (!greeted && uplink.isConnected && player != null) {
            greeted = true
            uplink.send(
                Messages.hello(
                    Config.MOD_VERSION,
                    client.launchedVersion,
                    player.uuid.toString(),
                    player.name.string,
                )
            )
        }
    }
}
