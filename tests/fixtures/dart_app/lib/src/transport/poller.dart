import '../alarm.dart';
import '../models.dart';
import 'retry.dart';

/// Polls a [ReadingSource] and feeds an [AlarmMonitor], backing off on bad lines.
class Poller {
  Poller(this.source, this.monitor, {Backoff? backoff})
      : _backoff = backoff ?? Backoff();

  final ReadingSource source;
  final AlarmMonitor monitor;
  final Backoff _backoff;

  /// Polls until the source runs dry, and returns how many readings it saw.
  Future<int> run() async {
    var seen = 0;
    var failures = 0;
    while (true) {
      try {
        final reading = await source.next();
        if (reading == null) return seen;
        monitor.record(reading);
        seen++;
        failures = 0;
        _backoff.reset();
      } on FormatException {
        failures++;
        if (!shouldRetry(failures)) rethrow;
        await Future<void>.delayed(_backoff.next());
      }
    }
  }
}
