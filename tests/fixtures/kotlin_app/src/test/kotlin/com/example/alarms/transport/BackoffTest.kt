package com.example.alarms.transport

import kotlin.test.Test
import kotlin.test.assertTrue

class BackoffTest {
    @Test
    fun delayGrows() {
        val backoff = Backoff()
        assertTrue(backoff.nextDelay(1) < backoff.nextDelay(2))
    }
}
