package com.example.sensors;

/** Something that wants to hear about alarms. */
@FunctionalInterface
public interface AlarmListener {
    /** Called once for every reading that raises an alarm. */
    void onAlarm(Reading reading, AlarmLevel level);
}
