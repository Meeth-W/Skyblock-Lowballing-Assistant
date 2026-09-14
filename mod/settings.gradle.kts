pluginManagement {
    repositories {
        maven("https://maven.fabricmc.net/")
        maven("https://maven.kikugie.dev/releases")
        maven("https://maven.kikugie.dev/snapshots")
        gradlePluginPortal()
        mavenCentral()
    }
}

plugins {
    id("dev.kikugie.stonecutter") version "0.7"
    // Both targets need Java 25. This fetches a matching JDK when the
    // machine does not have one, so the build does not depend on whatever
    // happens to be installed.
    id("org.gradle.toolchains.foojay-resolver-convention") version "1.0.0"
}

// Stonecutter is configured from the first commit, not retrofitted later.
// Hypixel SkyBlock permits only the two most recent content drops, so 26.1.2
// is already near the bottom of the supported window and will be cut when
// 26.3 ships. Adding a version here should be a one-line change, which it is
// only if the multi-version layout exists before it is needed.
stonecutter {
    create(rootProject) {
        versions("26.1.2", "26.2")
        vcsVersion = "26.1.2"
    }
}

rootProject.name = "lowball-mod"
