# src/main/java/com/example/sensors/  (5 files, 13 symbols) — Sensor readings and the alarms they raise
## AlarmLevel.java
- L4  enum AlarmLevel — How serious an alarm is
- L10    method AlarmLevel forPpm(double ppm) — The level for a concentration in ppm
## AlarmListener.java
- L4  interface AlarmListener — Something that wants to hear about alarms
- L7    method void onAlarm(Reading reading, AlarmLevel level) — Called once for every reading that raises an alarm
## App.java
- L10  class App — Entry point: checks one reading and reports an alarm
- L11    method void main(String[] args)
## Reading.java
- L8  class Reading — One reading from a gas sensor, in parts per million
- L10    const double DEFAULT_THRESHOLD = 40.0 — Readings above this many ppm raise an alarm
- L16    method Reading(String sensorId, double ppm, Instant takenAt)
- L23    method boolean isAlarm(double threshold) — True when the reading crosses the alarm threshold
- L28    method AlarmLevel level() — The alarm level for this reading
- L32    method String sensorId()
- L36    method double ppm()
## package-info.java — Sensor readings and the alarms they raise
