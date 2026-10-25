# src/main/kotlin/com/example/alarms/  (4 files, 14 symbols)
## AlarmLevel.kt
- L4  enum AlarmLevel — How serious an alarm is
- L11    method forPpm(ppm: Double): AlarmLevel — The level for a concentration in ppm
## Main.kt
- L8  fn main(args: Array<String>) — Reads one "sensor,ppm" line from the arguments and notifies on an alarm
## Notifier.kt
- L4  interface Notifier — Something that tells people about alarms
- L6    method notify(reading: Reading, level: AlarmLevel): Boolean — Sends one alarm; returns false when nobody could be reached
- L10  class ConsoleNotifier : Notifier — Prints alarms instead of sending them, for local runs
- L11    method notify(reading: Reading, level: AlarmLevel): Boolean
## Reading.kt
- L6  const DEFAULT_THRESHOLD = 40.0 — Readings at or above this many ppm raise an alarm
- L11  class Reading(val sensorId: String, val ppm: Double, val takenAt: Instant) — One reading from a gas sensor, in parts per million
- L13    method isAlarm(threshold: Double = DEFAULT_THRESHOLD): Boolean — True when the reading crosses threshold
- L16    method level(): AlarmLevel — The alarm level for this reading
- L18    method rounded(): Long
- L22    method parse(line: String): Reading — A reading parsed from "sensor,ppm"
- L30  fn List<Reading>.alarms(threshold: Double = DEFAULT_THRESHOLD): List<Reading> — The readings in this list that raise an alarm
