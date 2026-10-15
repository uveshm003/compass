package com.example.sensors;

import java.time.Instant;

/**
 * One reading from a gas sensor, in parts per million.
 */
public final class Reading {
    /** Readings above this many ppm raise an alarm. */
    public static final double DEFAULT_THRESHOLD = 40.0;

    private final String sensorId;
    private final double ppm;
    private final Instant takenAt;

    public Reading(String sensorId, double ppm, Instant takenAt) {
        this.sensorId = sensorId;
        this.ppm = ppm;
        this.takenAt = takenAt;
    }

    /** True when the reading crosses the alarm threshold. */
    public boolean isAlarm(double threshold) {
        return ppm >= threshold;
    }

    /** The alarm level for this reading. */
    public AlarmLevel level() {
        return AlarmLevel.forPpm(ppm);
    }

    public String sensorId() {
        return sensorId;
    }

    double ppm() {
        return ppm;
    }
}
