package com.example.alarms

import java.time.Instant

/** Readings at or above this many ppm raise an alarm. */
const val DEFAULT_THRESHOLD = 40.0

/**
 * One reading from a gas sensor, in parts per million.
 */
data class Reading(val sensorId: String, val ppm: Double, val takenAt: Instant) {
    /** True when the reading crosses [threshold]. */
    fun isAlarm(threshold: Double = DEFAULT_THRESHOLD): Boolean = ppm >= threshold

    /** The alarm level for this reading. */
    fun level(): AlarmLevel = AlarmLevel.forPpm(ppm)

    private fun rounded(): Long = Math.round(ppm)

    companion object {
        /** A reading parsed from "sensor,ppm". */
        fun parse(line: String): Reading {
            val (sensor, ppm) = line.split(",")
            return Reading(sensor, ppm.toDouble(), Instant.now())
        }
    }
}

/** The readings in this list that raise an alarm. */
fun List<Reading>.alarms(threshold: Double = DEFAULT_THRESHOLD): List<Reading> = filter { it.isAlarm(threshold) }
