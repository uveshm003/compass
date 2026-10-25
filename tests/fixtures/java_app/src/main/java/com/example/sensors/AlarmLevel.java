package com.example.sensors;

/** How serious an alarm is. */
public enum AlarmLevel {
    NONE,
    WARNING,
    CRITICAL;

    /** The level for a concentration in ppm. */
    public static AlarmLevel forPpm(double ppm) {
        if (ppm >= 100.0) {
            return CRITICAL;
        }
        return ppm >= Reading.DEFAULT_THRESHOLD ? WARNING : NONE;
    }
}
