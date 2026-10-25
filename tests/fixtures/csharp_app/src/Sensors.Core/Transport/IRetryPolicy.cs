namespace Sensors.Core.Transport;

/// <summary>
/// Decides how long to wait before each retry, and when to give up.
/// </summary>
public interface IRetryPolicy
{
    /// <summary>
    /// Delay before the given attempt, counting from 1.
    /// </summary>
    TimeSpan NextDelay(int attempt);

    /// <summary>
    /// Whether another attempt is allowed.
    /// </summary>
    bool ShouldRetry(int attempt);
}
