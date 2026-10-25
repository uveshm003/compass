namespace Sensors.Core.Transport;

/// <summary>
/// Exponential backoff with a cap, for flaky gateway links.
/// </summary>
public sealed class Backoff : IRetryPolicy
{
    /// <summary>
    /// Attempts allowed before giving up.
    /// </summary>
    public const int MaxAttempts = 5;

    private static readonly TimeSpan BaseDelay = TimeSpan.FromMilliseconds(100);

    private readonly TimeSpan _cap;

    public Backoff(TimeSpan cap)
    {
        _cap = cap;
    }

    /// <summary>
    /// The longest delay this policy ever returns.
    /// </summary>
    public TimeSpan Cap => _cap;

    /// <inheritdoc />
    public TimeSpan NextDelay(int attempt)
    {
        var delay = BaseDelay * Math.Pow(2, Math.Min(attempt, 16) - 1);
        return delay < _cap ? delay : _cap;
    }

    /// <inheritdoc />
    public bool ShouldRetry(int attempt) => attempt < MaxAttempts;
}
