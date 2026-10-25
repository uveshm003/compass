package com.example.alarms

/** How serious an alarm is. */
enum class AlarmLevel {
    NONE,
    WARNING,
    CRITICAL;

    companion object {
        /** The level for a concentration in ppm. */
        fun forPpm(ppm: Double): AlarmLevel = when {
            ppm >= 100.0 -> CRITICAL
            ppm >= DEFAULT_THRESHOLD -> WARNING
            else -> NONE
        }
    }
}
