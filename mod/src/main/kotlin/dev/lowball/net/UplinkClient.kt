package dev.lowball.net

import java.net.URI
import java.net.http.HttpClient
import java.net.http.WebSocket
import java.time.Duration
import java.util.concurrent.CompletionStage
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

/**
 * Outbound link to the desktop app.
 *
 * Uses the JDK's own WebSocket client, so the mod ships no extra jars. It
 * connects to loopback, sends, and reconnects when the app is not running.
 *
 * **This client never acts on anything it receives.** The listener below
 * discards incoming frames deliberately: an app-to-mod channel would be the
 * first step toward external software causing a gameplay action, which is what
 * Hypixel's rules prohibit and what would put the account at risk. Frames are
 * consumed only to keep the socket's flow control moving.
 *
 * Sending is queued and done off the render thread. Nothing here blocks the
 * game: if the app is down, messages are dropped rather than buffered without
 * limit, because a stale trade snapshot is worth nothing once the customer has
 * moved on.
 */
class UplinkClient(
    private val host: String = "127.0.0.1",
    private val port: Int = 8765,
    private val maxQueued: Int = 64,
) {
    private val socket = AtomicReference<WebSocket?>(null)
    private val connecting = AtomicBoolean(false)
    private val running = AtomicBoolean(false)
    private val pending = ConcurrentLinkedQueue<String>()
    private val http: HttpClient = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(3))
        .build()
    private val scheduler: ScheduledExecutorService =
        Executors.newSingleThreadScheduledExecutor { runnable ->
            Thread(runnable, "lowball-uplink").apply { isDaemon = true }
        }

    private var backoffSeconds = 1L

    val isConnected: Boolean
        get() = socket.get() != null

    fun start() {
        if (!running.compareAndSet(false, true)) return
        scheduler.execute(::connect)
        // A periodic heartbeat lets the app show an honest connection state
        // rather than one that is only correct while a trade is open.
        scheduler.scheduleAtFixedRate({ heartbeat() }, 15, 15, TimeUnit.SECONDS)
    }

    fun stop() {
        if (!running.compareAndSet(true, false)) return
        socket.getAndSet(null)?.sendClose(WebSocket.NORMAL_CLOSURE, "client shutting down")
        scheduler.shutdownNow()
    }

    /** Queue a JSON frame. Safe to call from any thread, including the client tick. */
    fun send(json: String) {
        if (!running.get()) return
        if (pending.size >= maxQueued) {
            // Drop the oldest: a trade snapshot from ten seconds ago is not
            // worth delaying the current one for.
            pending.poll()
        }
        pending.add(json)
        scheduler.execute(::drain)
    }

    private fun heartbeat() {
        if (isConnected) {
            send("""{"type":"heartbeat","ts":"${java.time.Instant.now()}"}""")
        } else {
            connect()
        }
    }

    private fun connect() {
        if (!running.get() || isConnected) return
        if (!connecting.compareAndSet(false, true)) return

        http.newWebSocketBuilder()
            .connectTimeout(Duration.ofSeconds(3))
            .buildAsync(URI.create("ws://$host:$port"), DiscardingListener())
            .whenComplete { established, error ->
                connecting.set(false)
                if (error != null || established == null) {
                    scheduleReconnect()
                    return@whenComplete
                }
                socket.set(established)
                backoffSeconds = 1
                onConnected?.invoke()
                drain()
            }
    }

    private fun scheduleReconnect() {
        if (!running.get()) return
        val delay = backoffSeconds
        // Capped exponential backoff: the app is often simply not running yet,
        // and hammering loopback once a second for an hour helps nobody.
        backoffSeconds = (backoffSeconds * 2).coerceAtMost(30)
        scheduler.schedule(::connect, delay, TimeUnit.SECONDS)
    }

    private fun drain() {
        val live = socket.get() ?: run {
            connect()
            return
        }
        while (true) {
            val next = pending.poll() ?: return
            try {
                live.sendText(next, true).exceptionally {
                    // The app went away mid-send. Drop the socket and let the
                    // reconnect loop pick it up.
                    handleDisconnect(live)
                    null
                }
            } catch (_: Exception) {
                handleDisconnect(live)
                return
            }
        }
    }

    private fun handleDisconnect(dead: WebSocket) {
        if (socket.compareAndSet(dead, null)) {
            onDisconnected?.invoke()
            scheduleReconnect()
        }
    }

    var onConnected: (() -> Unit)? = null
    var onDisconnected: (() -> Unit)? = null

    /**
     * Consumes incoming frames and acts on none of them.
     *
     * The app has no channel into the game and this is where that is enforced.
     * If a future change needs the app to influence the mod, it does not go
     * here: it goes in the app's own UI.
     */
    private inner class DiscardingListener : WebSocket.Listener {
        override fun onOpen(webSocket: WebSocket) {
            webSocket.request(1)
        }

        override fun onText(
            webSocket: WebSocket,
            data: CharSequence,
            last: Boolean,
        ): CompletionStage<*>? {
            webSocket.request(1)
            return null
        }

        override fun onError(webSocket: WebSocket, error: Throwable) {
            handleDisconnect(webSocket)
        }

        override fun onClose(
            webSocket: WebSocket,
            statusCode: Int,
            reason: String,
        ): CompletionStage<*>? {
            handleDisconnect(webSocket)
            return null
        }
    }
}
