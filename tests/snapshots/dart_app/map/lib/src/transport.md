# lib/src/transport/  (2 files, 12 symbols)
## poller.dart
- L6  class Poller — Polls a ReadingSource and feeds an AlarmMonitor, backing off on bad lines
- L7    method Poller(this.source, this.monitor, {Backoff? backoff})
- L15    method Future<int> run() — Polls until the source runs dry, and returns how many readings it saw
## retry.dart
- L4  const int maxAttempts = 5 — Most attempts before a poll gives up
- L7  class Backoff with RetryLog — Exponential backoff with full jitter
- L8    method Backoff({this.base = const Duration(milliseconds: 100), Random? random})
- L16    method Duration next() — The delay before the next attempt
- L25    method void reset() — Starts again from the first attempt
- L29  trait RetryLog — Keeps a record of each retry, for diagnostics
- L33    method List<String> get entries — The retries so far, oldest first
- L35    method void logRetry(int attempt, Duration delay)
- L40  fn bool shouldRetry(int attempt) — Whether another attempt is allowed after attempt failures
