# src/Sensors.Core/Alarms/  (1 file, 7 symbols)
## AlarmEvaluator.cs
- L4  namespace Sensors.Core.Alarms
- L9    class AlarmEvaluator — Turns readings into alarm levels and logs the critical ones
- L11      const double CriticalFactor = 2.0
- L16      method AlarmEvaluator(ILogger<AlarmEvaluator> logger, double threshold = Reading.DefaultThreshold)
- L25      method AlarmLevel Classify(Reading reading) — Classifies one reading against the configured threshold
- L37      method IReadOnlyList<AlarmLevel> ClassifyAll(IEnumerable<Reading> readings) — Classifies a batch of readings and logs every critical one
- L52      method void LogCritical(Reading reading)
