# lib/src/  (2 files, 22 symbols)
## alarm.dart — Alarm levels and the monitor that raises them
- L7  enum AlarmLevel — How serious an alarm is
- L12    method AlarmLevel(this.severity)
- L18    method bool get pages — Whether someone should be paged
- L22  type AlarmCallback = void Function(String sensorId, AlarmLevel level) — Called whenever a sensor's alarm level changes
- L25  class AlarmMonitor — Tracks the last alarm level of each sensor and reports changes
- L26    method AlarmMonitor(this._onChange, {this.threshold = defaultThreshold})
- L33    method AlarmLevel record(Reading reading) — Records reading and returns its alarm level
- L43    method void _reset() — Forgets every sensor, so the next reading of each reports again
- L47  fn AlarmLevel classify(Reading reading, double threshold) — The alarm level for reading: critical at twice the threshold
## models.dart — Sensor readings and the sources that produce them
- L5  const double defaultThreshold = 50.0 — Alarm threshold, in ppm, for a sensor that has none of its own
- L8  enum SensorKind — The kinds of sensor a reading can come from
- L11  class Reading — One measurement from one sensor
- L13    method Reading(this.sensorId, this.value, {this.kind = SensorKind.gas}) — Creates a reading of value from sensorId
- L16    method zero(this.sensorId) — A reading of zero, used before a sensor reports
- L21    method parse(String line) — Parses `id:value`, the form sensors send over the wire
- L32    method bool isAlarm([double threshold = defaultThreshold]) — True when the reading crosses threshold
- L34    method String toString()
- L39  interface ReadingSource — Anything that produces readings: a device, a recording, a test double
- L41    method Future<Reading?> next() — The next reading, or null once the source is exhausted
- L44    method String get name — A name for logs
- L48  impl ReadingFormat on Reading — Formatting for dashboards
- L50    method String get label — The value with its unit, such as `52.0 ppm`
