package com.example.alarms

/** Something that tells people about alarms. */
interface Notifier {
    /** Sends one alarm; returns false when nobody could be reached. */
    suspend fun notify(reading: Reading, level: AlarmLevel): Boolean
}

/** Prints alarms instead of sending them, for local runs. */
internal object ConsoleNotifier : Notifier {
    override suspend fun notify(reading: Reading, level: AlarmLevel): Boolean {
        println("${reading.sensorId}: $level")
        return true
    }
}
