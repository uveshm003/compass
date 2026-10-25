package com.example.sensors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Instant;
import org.junit.jupiter.api.Test;

class ReadingTest {
    @Test
    void alarmAtThreshold() {
        assertTrue(new Reading("s1", 40.0, Instant.EPOCH).isAlarm(Reading.DEFAULT_THRESHOLD));
    }

    @Test
    void criticalAboveHundred() {
        assertEquals(AlarmLevel.CRITICAL, new Reading("s1", 120.0, Instant.EPOCH).level());
    }
}
