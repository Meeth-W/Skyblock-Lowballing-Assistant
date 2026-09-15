package dev.lowball

import java.nio.file.Files
import java.nio.file.Path
import java.util.Properties
import net.fabricmc.loader.api.FabricLoader
import org.slf4j.LoggerFactory

/**
 * Where to find the desktop app, and nothing else.
 *
 * Deliberately two settings. The mod is a dumb pipe; every decision that
 * matters is made in the desktop app, which is what keeps the quarterly
 * Minecraft version bumps cheap. The port is here only because two programs
 * have to agree on it and one of them may already be using 8765 for something
 * else.
 *
 * Stored as a `.properties` file rather than JSON: it is the one format the
 * JDK already parses, so the mod ships no serialisation library for four
 * lines of configuration, and a user can open it and see what it says.
 *
 * The version is read from the mod's own metadata rather than repeated here.
 * It goes out in the `hello` frame and the app logs it, so a copy that drifts
 * from `gradle.properties` is a bug report that sends everyone to the wrong
 * release.
 */
object Config {

    const val MOD_ID: String = "lowball"

    private val log = LoggerFactory.getLogger("lowball")

    var host: String = "127.0.0.1"
        private set

    var port: Int = 8765
        private set

    val modVersion: String by lazy {
        FabricLoader.getInstance()
            .getModContainer(MOD_ID)
            .map { it.metadata.version.friendlyString }
            .orElse("unknown")
    }

    /**
     * Read the config file, writing it out first if it is not there.
     *
     * Any unreadable value falls back to the default rather than failing: a
     * mod that refuses to load because of a stray character in a port number
     * is worse than one that quietly uses 8765 and says so in the log.
     */
    fun load(path: Path = defaultPath()) {
        try {
            if (Files.notExists(path)) {
                write(path)
                return
            }
            val properties = Properties()
            Files.newBufferedReader(path).use(properties::load)
            host = properties.getProperty("host")?.trim().orEmpty().ifEmpty { host }
            properties.getProperty("port")?.trim()?.toIntOrNull()?.let {
                if (it in 1..65535) port = it else log.warn("Lowball: port {} out of range", it)
            }
        } catch (exception: Exception) {
            log.warn("Lowball: could not read {}, using defaults: {}", path, exception.toString())
        }
        log.info("Lowball: uplink target is ws://{}:{}", host, port)
    }

    private fun defaultPath(): Path =
        FabricLoader.getInstance().configDir.resolve("$MOD_ID.properties")

    private fun write(path: Path) {
        try {
            Files.createDirectories(path.parent)
            Files.writeString(path, DEFAULT_FILE)
        } catch (exception: Exception) {
            log.warn("Lowball: could not write {}: {}", path, exception.toString())
        }
    }

    private val DEFAULT_FILE: String =
        """
        # Lowball Uplink
        #
        # Where the desktop app is listening. Loopback only: the app runs on
        # this machine, and the mod has no reason to reach any further.
        #
        # Change this only if something else on your machine already has 8765.
        # The app takes the same number with --port.
        host=127.0.0.1
        port=8765
        """.trimIndent() + "\n"
}
