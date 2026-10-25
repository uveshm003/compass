# include/sensors/  (1 file, 12 symbols)
## alarm.hpp — Alarm thresholds and the monitor that applies them
- L8  namespace sensors
- L11  enum Level — Severity of a reading against its threshold
- L14  const double kDefaultThreshold = 50.0 — Default alarm threshold, in ppm
- L17  struct Reading — A reading from one gas sensor
- L22    method bool is_alarm(double threshold = kDefaultThreshold) const — True when the reading crosses the alarm threshold
- L26  class AlarmMonitor — Watches readings and counts the alarms they raise
- L28    method AlarmMonitor(double threshold)
- L31    method Level classify(const Reading& reading) — Classify a reading and record any alarm
- L34    method int alarms() const — Alarms raised so far
- L37    method void on_alarm(const Reading& reading)
- L40    method void record(Level level)
- L46  fn T clamp_ppm(T value, T limit)
