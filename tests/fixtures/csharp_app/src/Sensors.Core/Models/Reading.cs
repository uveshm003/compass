namespace Sensors.Core.Models;

/// <summary>
/// How serious a reading is, from normal to critical.
/// </summary>
public enum AlarmLevel
{
    Normal,
    Warning,
    Critical,
}

/// <summary>
/// One measurement from a gas sensor, in parts per million.
/// </summary>
/// <param name="SensorId">The sensor's serial number.</param>
/// <param name="Ppm">The measured concentration.</param>
public record Reading(string SensorId, double Ppm)
{
    /// <summary>
    /// Concentration at which a reading raises an alarm.
    /// </summary>
    public const double DefaultThreshold = 50.0;

    /// <summary>
    /// True when the reading crosses the alarm threshold.
    /// </summary>
    public bool IsAlarm(double threshold = DefaultThreshold) => Ppm >= threshold;
}
