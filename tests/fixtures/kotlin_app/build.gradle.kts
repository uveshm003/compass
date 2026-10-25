plugins {
    alias(libs.plugins.kotlin.jvm)
    alias(libs.plugins.detekt)
    application
}

group = "com.example"
version = "0.9.1"

kotlin {
    jvmToolchain(21)
}

dependencies {
    implementation(libs.kotlinx.coroutines.core)
    implementation(libs.ktor.client.core)
    testImplementation(kotlin("test"))
    testImplementation(libs.kotlinx.coroutines.test)
}

application {
    mainClass = "com.example.alarms.MainKt"
}

tasks.test {
    useJUnitPlatform()
}
