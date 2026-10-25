# src/Sensors.Core/Models/  (1 file, 5 symbols)
## Reading.cs
- L1  namespace Sensors.Core.Models
- L6  enum AlarmLevel — How serious a reading is, from normal to critical
- L18  class Reading(string SensorId, double Ppm) — One measurement from a gas sensor, in parts per million
- L23    const double DefaultThreshold = 50.0 — Concentration at which a reading raises an alarm
- L28    method bool IsAlarm(double threshold = DefaultThreshold) — True when the reading crosses the alarm threshold
