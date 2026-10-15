# src/  (3 files, 13 symbols)
## alarm.cpp
- L5  namespace sensors
- L9  fn const char* label(Level level) — Label used in log lines
- L23  method bool Reading::is_alarm(double threshold) const
- L28  method AlarmMonitor.AlarmMonitor(double threshold) : threshold_(threshold)
- L30  method Level AlarmMonitor::classify(const Reading& reading)
- L40  method void AlarmMonitor::on_alarm(const Reading& reading)
- L45  method void AlarmMonitor::record(Level level)
## main.cpp — Gateway entry point: polls the sensors and reports alarms
- L8  fn int main()
## retry.c
- L6  const millis_t max_delay_ms = 30000 — Upper bound for a single delay
- L11  fn millis_t clamp_delay(millis_t delay) — Never wait longer than max_delay_ms
- L16  fn millis_t backoff_next_delay(struct backoff *b)
- L22  fn void backoff_reset(backoff_t *b)
- L29  fn retry_result retry_step(backoff_t *b, int ok)
