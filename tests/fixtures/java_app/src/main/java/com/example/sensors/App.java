package com.example.sensors;

import static com.example.sensors.transport.RetryPolicy.MAX_ATTEMPTS;

import com.example.sensors.transport.RetryPolicy;
import java.time.Duration;
import java.time.Instant;

/** Entry point: checks one reading and reports an alarm. */
public class App {
    public static void main(String[] args) {
        RetryPolicy retry = new RetryPolicy(Duration.ofMillis(200));
        Reading reading = new Reading("s1", Double.parseDouble(args[0]), Instant.now());
        AlarmListener listener = (r, level) -> System.out.println(r.sensorId() + " " + level);
        if (reading.isAlarm(Reading.DEFAULT_THRESHOLD)) {
            listener.onAlarm(reading, reading.level());
        }
        System.out.println("next retry in " + retry.nextDelay(1) + " of " + MAX_ATTEMPTS);
    }
}
