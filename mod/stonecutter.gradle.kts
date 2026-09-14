plugins {
    id("dev.kikugie.stonecutter")
}

// The version the IDE and a plain `gradlew build` work against.
stonecutter active "26.1.2"

// Registers chiseled variants, so `gradlew chiseledBuild` builds every
// configured version in one pass rather than one switch at a time.
stonecutter.tasks {
    named("build")
}
