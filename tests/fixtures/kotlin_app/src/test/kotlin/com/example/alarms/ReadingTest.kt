package com.example.alarms

import java.time.Instant
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ReadingTest {
    @Test
    fun alarmAtThreshold() {
        assertTrue(Reading("s1", 40.0, Instant.EPOCH).isAlarm())
    }

    @Test
    fun parsesALine() {
        assertEquals(AlarmLevel.CRITICAL, Reading.parse("s1,120").level())
    }
}
