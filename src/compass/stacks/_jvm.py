"""Shared by the Maven and Gradle detectors: which JVM libraries and plugins
count as frameworks and tools, under short names a prompt would use."""

from __future__ import annotations

# group or group:artifact-prefix -> short name; longest prefix wins.
FRAMEWORKS = {
    "androidx.compose": "compose",
    "ch.qos.logback": "logback",
    "com.fasterxml.jackson": "jackson",
    "com.google.dagger": "dagger",
    "com.google.guava": "guava",
    "com.squareup.okhttp3": "okhttp",
    "com.squareup.retrofit2": "retrofit",
    "io.dropwizard": "dropwizard",
    "io.grpc": "grpc",
    "io.insert-koin": "koin",
    "io.ktor": "ktor",
    "io.micronaut": "micronaut",
    "io.projectreactor": "reactor",
    "io.quarkus": "quarkus",
    "io.reactivex.rxjava3": "rxjava",
    "io.vertx": "vertx",
    "org.apache.kafka": "kafka",
    "org.apache.logging.log4j": "log4j",
    "org.hibernate.orm": "hibernate",
    "org.jetbrains.exposed": "exposed",
    "org.jetbrains.kotlinx:kotlinx-coroutines": "kotlinx-coroutines",
    "org.jetbrains.kotlinx:kotlinx-serialization": "kotlinx-serialization",
    "org.jooq": "jooq",
    "org.mybatis": "mybatis",
    "org.slf4j": "slf4j",
    "org.springframework": "spring",
    "org.springframework.boot": "spring-boot",
}
TOOLS = {
    "io.kotest": "kotest",
    "io.mockk": "mockk",
    "junit:junit": "junit",
    "org.assertj": "assertj",
    "org.jetbrains.kotlin:kotlin-test": "kotlin-test",
    "org.junit.jupiter": "junit",
    "org.mockito": "mockito",
    "org.testcontainers": "testcontainers",
}
# Gradle plugin ids and Maven plugin artifacts that name a tool or framework.
PLUGINS = {
    "checkstyle": ("tools", "checkstyle"),
    "com.android.application": ("frameworks", "android"),
    "com.android.library": ("frameworks", "android"),
    "com.diffplug.spotless": ("tools", "spotless"),
    "io.gitlab.arturbosch.detekt": ("tools", "detekt"),
    "io.quarkus": ("frameworks", "quarkus"),
    "jacoco": ("tools", "jacoco"),
    "jacoco-maven-plugin": ("tools", "jacoco"),
    "maven-checkstyle-plugin": ("tools", "checkstyle"),
    "org.jlleitschuh.gradle.ktlint": ("tools", "ktlint"),
    "org.springframework.boot": ("frameworks", "spring-boot"),
    "spotless-maven-plugin": ("tools", "spotless"),
    "spring-boot-maven-plugin": ("frameworks", "spring-boot"),
}
KOTLIN_PLUGINS = ("org.jetbrains.kotlin.jvm", "org.jetbrains.kotlin.android", "org.jetbrains.kotlin.multiplatform")


def classify(coordinates: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """``{"group:artifact": version}`` to (frameworks, tools) under short names."""
    frameworks: dict[str, str] = {}
    tools: dict[str, str] = {}
    for coordinate in sorted(coordinates):
        for table, out in ((FRAMEWORKS, frameworks), (TOOLS, tools)):
            name = _short_name(table, coordinate)
            if name and not out.get(name):
                out[name] = coordinates[coordinate]
    return frameworks, tools


def _short_name(table: dict[str, str], coordinate: str) -> str | None:
    group = coordinate.split(":", 1)[0]
    best = None
    for prefix, name in table.items():
        matches = coordinate.startswith(prefix) if ":" in prefix else group == prefix or group.startswith(prefix + ".")
        if matches and (best is None or len(prefix) > len(best[0])):
            best = (prefix, name)
    return best[1] if best else None
