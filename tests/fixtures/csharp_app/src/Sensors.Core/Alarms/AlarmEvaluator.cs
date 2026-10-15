using Microsoft.Extensions.Logging;
using Sensors.Core.Models;

namespace Sensors.Core.Alarms
{
    /// <summary>
    /// Turns readings into alarm levels and logs the critical ones.
    /// </summary>
    public class AlarmEvaluator
    {
        private const double CriticalFactor = 2.0;

        private readonly ILogger<AlarmEvaluator> _logger;
        private readonly double _threshold;

        public AlarmEvaluator(ILogger<AlarmEvaluator> logger, double threshold = Reading.DefaultThreshold)
        {
            _logger = logger;
            _threshold = threshold;
        }

        /// <summary>
        /// Classifies one reading against the configured threshold.
        /// </summary>
        public AlarmLevel Classify(Reading reading)
        {
            if (!reading.IsAlarm(_threshold))
            {
                return AlarmLevel.Normal;
            }
            return reading.Ppm >= _threshold * CriticalFactor ? AlarmLevel.Critical : AlarmLevel.Warning;
        }

        /// <summary>
        /// Classifies a batch of readings and logs every critical one.
        /// </summary>
        public IReadOnlyList<AlarmLevel> ClassifyAll(IEnumerable<Reading> readings)
        {
            var levels = new List<AlarmLevel>();
            foreach (var reading in readings)
            {
                var level = Classify(reading);
                if (level == AlarmLevel.Critical)
                {
                    LogCritical(reading);
                }
                levels.Add(level);
            }
            return levels;
        }

        private void LogCritical(Reading reading) =>
            _logger.LogWarning("Critical reading of {Ppm} ppm from {SensorId}", reading.Ppm, reading.SensorId);
    }
}
