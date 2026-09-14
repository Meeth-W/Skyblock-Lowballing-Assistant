package dev.lowball

/**
 * Everything the mod lets you change: the port and the select-tool key.
 *
 * Deliberately nothing else. The mod is a dumb pipe; every decision that
 * matters is made in the desktop app, which is what keeps the quarterly
 * Minecraft version bumps cheap.
 */
object Config {
    const val HOST: String = "127.0.0.1"
    const val PORT: Int = 8765

    const val MOD_VERSION: String = "0.2.0"
}
