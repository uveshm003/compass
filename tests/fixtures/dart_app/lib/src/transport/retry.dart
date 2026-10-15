import 'dart:math';

/// Most attempts before a poll gives up.
const int maxAttempts = 5;

/// Exponential backoff with full jitter.
class Backoff with RetryLog {
  Backoff({this.base = const Duration(milliseconds: 100), Random? random})
      : _random = random ?? Random();

  final Duration base;
  final Random _random;
  int _attempt = 0;

  /// The delay before the next attempt.
  Duration next() {
    _attempt++;
    final cap = base.inMilliseconds * pow(2, min(_attempt, 8)).toInt();
    final delay = Duration(milliseconds: _random.nextInt(cap + 1));
    logRetry(_attempt, delay);
    return delay;
  }

  /// Starts again from the first attempt.
  void reset() => _attempt = 0;
}

/// Keeps a record of each retry, for diagnostics.
mixin RetryLog {
  final List<String> _entries = [];

  /// The retries so far, oldest first.
  List<String> get entries => List.unmodifiable(_entries);

  void logRetry(int attempt, Duration delay) =>
      _entries.add('attempt $attempt after ${delay.inMilliseconds} ms');
}

/// Whether another attempt is allowed after [attempt] failures.
bool shouldRetry(int attempt) => attempt < maxAttempts;
