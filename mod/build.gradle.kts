plugins {
    kotlin("jvm") version "2.4.20"
    // `net.fabricmc.fabric-loom`, not `fabric-loom-remap`. From 26.1 the game
    // ships fully unobfuscated -- its version manifest carries no
    // `client_mappings` at all, because there is nothing to deobfuscate -- so
    // there is no mappings dependency, no remapping step, and dependencies are
    // plain `implementation` rather than `modImplementation`.
    id("net.fabricmc.fabric-loom") version "1.17-SNAPSHOT"
    id("dev.kikugie.stonecutter")
}

/** The Minecraft version this Stonecutter node targets. */
val mcVersion: String = stonecutter.current.version

/** Per-version dependency coordinates, resolved from the Fabric maven. */
data class Target(val fabricApi: String, val fabricKotlin: String)

val targets = mapOf(
    "26.1.2" to Target(fabricApi = "0.155.3+26.1.2", fabricKotlin = "1.14.1+kotlin.2.4.20"),
    "26.2" to Target(fabricApi = "0.160.0+26.2", fabricKotlin = "1.14.1+kotlin.2.4.20"),
)
val target = targets.getValue(mcVersion)

group = property("mod.group")!!
version = "${property("mod.version")}+$mcVersion"
base.archivesName = "${property("mod.id")}-$mcVersion"

repositories {
    maven("https://maven.fabricmc.net/")
    mavenCentral()
}

dependencies {
    minecraft("com.mojang:minecraft:$mcVersion")
    implementation("net.fabricmc:fabric-loader:${property("deps.fabric_loader")}")
    implementation("net.fabricmc.fabric-api:fabric-api:${target.fabricApi}")
    implementation("net.fabricmc:fabric-language-kotlin:${target.fabricKotlin}")
    // No WebSocket library: java.net.http.WebSocket is in the JDK, and a mod
    // that ships fewer jars is a mod that breaks less often on a version bump.
}

val javaVersion = (property("mod.java") as String).toInt()

java {
    withSourcesJar()
    sourceCompatibility = JavaVersion.toVersion(javaVersion)
    targetCompatibility = JavaVersion.toVersion(javaVersion)
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.fromTarget(javaVersion.toString())
    }
}

tasks.withType<JavaCompile>().configureEach {
    options.release = javaVersion
    options.encoding = "UTF-8"
}

// Read at configuration time, outside the task block: inside it, `property`
// would resolve against the task rather than the project.
val templateValues = mapOf(
    "id" to property("mod.id"),
    "name" to property("mod.name"),
    "version" to version,
    "mc" to mcVersion,
    "java" to javaVersion,
    "loader" to property("deps.fabric_loader"),
)

tasks.processResources {
    inputs.properties(templateValues)
    filesMatching("fabric.mod.json") { expand(templateValues) }
}
