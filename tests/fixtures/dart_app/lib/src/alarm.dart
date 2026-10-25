/// Alarm levels and the monitor that raises them.
library;

import 'models.dart';

/// How serious an alarm is.
enum AlarmLevel {
  none(0),
  warning(1),
  critical(2);

  const AlarmLevel(this.severity);

  /// Higher is worse.
  final int severity;

  /// Whether someone should be paged.
  bool get pages => this == AlarmLevel.critical;
}

/// Called whenever a sensor's alarm level changes.
typedef AlarmCallback = void Function(String sensorId, AlarmLevel level);

/// Tracks the last alarm level of each sensor and reports changes.
class AlarmMonitor {
  AlarmMonitor(this._onChange, {this.threshold = defaultThreshold});

  final AlarmCallback _onChange;
  final double threshold;
  final Map<String, AlarmLevel> _levels = {};

  /// Records [reading] and returns its alarm level.
  AlarmLevel record(Reading reading) {
    final level = classify(reading, threshold);
    if (_levels[reading.sensorId] != level) {
      _levels[reading.sensorId] = level;
      _onChange(reading.sensorId, level);
    }
    return level;
  }

  /// Forgets every sensor, so the next reading of each reports again.
  void _reset() => _levels.clear();
}

/// The alarm level for [reading]: critical at twice the threshold.
AlarmLevel classify(Reading reading, double threshold) {
  if (reading.isAlarm(threshold * 2)) return AlarmLevel.critical;
  if (reading.isAlarm(threshold)) return AlarmLevel.warning;
  return AlarmLevel.none;
}
