# src/main/java/com/example/sensors/transport/  (1 file, 5 symbols)
## RetryPolicy.java
- L8  class RetryPolicy — Exponential backoff for forwarding readings upstream
- L10    const int MAX_ATTEMPTS = 5 — Attempts allowed before a reading is dropped
- L14    method RetryPolicy(Duration base)
- L19    method Duration nextDelay(int attempt) — Delay before the given attempt, doubling each time and capped
- L24    method boolean shouldRetry(int attempt) — Whether another attempt is allowed
