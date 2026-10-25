package com.example.alarms.transport

import kotlinx.coroutines.delay
import kotlin.time.Duration
import kotlin.time.Duration.Companion.milliseconds

/** Attempts allowed before a notification is dropped. */
const val MAX_ATTEMPTS = 5

/**
 * Exponential backoff with a cap.
 */
class Backoff(private val base: Duration = 200.milliseconds) {
    /** Delay before the given attempt, doubling each time. */
    fun nextDelay(attempt: Int): Duration = base * (1 shl minOf(attempt, 6))
}

/** Runs [block] until it succeeds or [MAX_ATTEMPTS] is reached. */
suspend fun retry(backoff: Backoff, block: suspend () -> Boolean): Boolean {
    repeat(MAX_ATTEMPTS) { attempt ->
        if (block()) return true
        delay(backoff.nextDelay(attempt))
    }
    return false
}
