using Microsoft.Extensions.Logging;

namespace Sensors.Core.Transport;

/// <summary>
/// Runs an operation until it succeeds or the policy gives up.
/// </summary>
public static class Retry
{
    /// <summary>
    /// Calls the operation until it succeeds, waiting between attempts as the policy says.
    /// </summary>
    public static async Task<T> RunAsync<T>(Func<CancellationToken, Task<T>> operation, IRetryPolicy policy, ILogger logger, CancellationToken token = default)
    {
        for (var attempt = 1; ; attempt++)
        {
            try
            {
                return await operation(token);
            }
            catch (IOException error) when (policy.ShouldRetry(attempt))
            {
                logger.LogDebug(error, "Attempt {Attempt} failed", attempt);
                await Task.Delay(policy.NextDelay(attempt), token);
            }
        }
    }
}

static class RetryDefaults
{
    /// <summary>
    /// The policy the gateway uses when none is configured.
    /// </summary>
    internal static Backoff Create() => new Backoff(TimeSpan.FromSeconds(30));
}
