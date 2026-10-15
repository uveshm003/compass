# src/Sensors.Core/Transport/  (3 files, 17 symbols)
## Backoff.cs
- L1  namespace Sensors.Core.Transport
- L6  class Backoff : IRetryPolicy — Exponential backoff with a cap, for flaky gateway links
- L11    const int MaxAttempts = 5 — Attempts allowed before giving up
- L13    const TimeSpan BaseDelay = TimeSpan.FromMilliseconds(100)
- L17    method Backoff(TimeSpan cap)
- L25    method TimeSpan Cap — The longest delay this policy ever returns
- L28    method TimeSpan NextDelay(int attempt)
- L35    method bool ShouldRetry(int attempt)
## IRetryPolicy.cs
- L1  namespace Sensors.Core.Transport
- L6  interface IRetryPolicy — Decides how long to wait before each retry, and when to give up
- L11    method TimeSpan NextDelay(int attempt) — Delay before the given attempt, counting from 1
- L16    method bool ShouldRetry(int attempt) — Whether another attempt is allowed
## Retry.cs
- L3  namespace Sensors.Core.Transport
- L8  class Retry — Runs an operation until it succeeds or the policy gives up
- L13    method Task<T> RunAsync<T>(Func<CancellationToken, Task<T>> operation, IRetryPolicy policy, ILogger logger, CancellationToken token = default) — Calls the operation until it succeeds, waiting between attempts as the policy says
- L30  class RetryDefaults
- L35    method Backoff Create() — The policy the gateway uses when none is configured
