package com.example.sensors.transport;

import static org.junit.jupiter.api.Assertions.assertFalse;

import java.time.Duration;
import org.junit.jupiter.api.Test;

class RetryPolicyTest {
    @Test
    void stopsAfterMaxAttempts() {
        assertFalse(new RetryPolicy(Duration.ofMillis(1)).shouldRetry(RetryPolicy.MAX_ATTEMPTS));
    }
}
