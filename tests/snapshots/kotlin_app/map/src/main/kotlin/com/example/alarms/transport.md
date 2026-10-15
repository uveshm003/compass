# src/main/kotlin/com/example/alarms/transport/  (1 file, 4 symbols)
## Backoff.kt
- L8  const MAX_ATTEMPTS = 5 — Attempts allowed before a notification is dropped
- L13  class Backoff(private val base: Duration = 200.milliseconds) — Exponential backoff with a cap
- L15    method nextDelay(attempt: Int): Duration — Delay before the given attempt, doubling each time
- L19  fn retry(backoff: Backoff, block: suspend () -> Boolean): Boolean — Runs block until it succeeds or MAX_ATTEMPTS is reached
