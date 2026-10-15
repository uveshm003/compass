# Sources/Inventory/  (2 files, 18 symbols)
## Reading.swift — Readings from gas sensors and the rule that turns one into an alarm
- L5  const defaultThreshold: Double = 40.0 — Concentration in ppm at which a reading counts as an alarm
- L8  enum Severity: String, Codable — How serious an alarm is
- L13    const criticalLevel: Double = 200.0 — Readings above this many ppm are critical
- L16    method of(ppm: Double) -> Severity — The severity of a concentration that already counts as an alarm
- L22  struct Reading: Codable, Equatable — A reading from one sensor
- L29    method init(sensorId: String, ppm: Double) — Creates a reading taken now
- L36    method isAlarm(threshold: Double = defaultThreshold) -> Bool — True when the reading crosses the alarm threshold
- L41    method severity() -> Severity? — The alarm's severity, or nil when the reading is not an alarm
- L45    method age(now: Date) -> TimeInterval
- L50  impl Reading: CustomStringConvertible
- L54    method isStale(after seconds: TimeInterval, now: Date = Date()) -> Bool — Whether the reading is older than `seconds`
## ReadingStore.swift
- L7  interface ReadingStore — Somewhere readings are kept until they are uploaded
- L9    method save(_ reading: Reading) throws — Keeps one reading
- L11    method pending() -> [Reading] — Readings not yet uploaded, oldest first
- L15  class MemoryStore: ReadingStore — A store that keeps readings in memory; used by tests and the simulator
- L19    method init()
- L21    method save(_ reading: Reading) throws
- L28    method pending() -> [Reading]
