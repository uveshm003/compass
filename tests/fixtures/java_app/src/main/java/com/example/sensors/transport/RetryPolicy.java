package com.example.sensors.transport;

import java.time.Duration;

/**
 * Exponential backoff for forwarding readings upstream.
 */
public class RetryPolicy {
    /** Attempts allowed before a reading is dropped. */
    public static final int MAX_ATTEMPTS = 5;

    private final Duration base;

    public RetryPolicy(Duration base) {
        this.base = base;
    }

    /** Delay before the given attempt, doubling each time and capped. */
    public Duration nextDelay(int attempt) {
        return base.multipliedBy(1L << Math.min(attempt, 6));
    }

    /** Whether another attempt is allowed. */
    public boolean shouldRetry(int attempt) {
        return attempt < MAX_ATTEMPTS;
    }
}
