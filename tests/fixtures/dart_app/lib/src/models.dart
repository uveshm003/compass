/// Sensor readings and the sources that produce them.
library;

/// Alarm threshold, in ppm, for a sensor that has none of its own.
const double defaultThreshold = 50.0;

/// The kinds of sensor a reading can come from.
enum SensorKind { gas, temperature, humidity }

/// One measurement from one sensor.
class Reading {
  /// Creates a reading of [value] from [sensorId].
  const Reading(this.sensorId, this.value, {this.kind = SensorKind.gas});

  /// A reading of zero, used before a sensor reports.
  const Reading.zero(this.sensorId)
      : value = 0,
        kind = SensorKind.gas;

  /// Parses `id:value`, the form sensors send over the wire.
  factory Reading.parse(String line) {
    final parts = line.split(':');
    if (parts.length != 2) throw FormatException('expected id:value', line);
    return Reading(parts[0], double.parse(parts[1]));
  }

  final String sensorId;
  final double value;
  final SensorKind kind;

  /// True when the reading crosses [threshold].
  bool isAlarm([double threshold = defaultThreshold]) => value > threshold;

  @override
  String toString() => 'Reading($sensorId, $value)';
}

/// Anything that produces readings: a device, a recording, a test double.
abstract interface class ReadingSource {
  /// The next reading, or null once the source is exhausted.
  Future<Reading?> next();

  /// A name for logs.
  String get name;
}

/// Formatting for dashboards.
extension ReadingFormat on Reading {
  /// The value with its unit, such as `52.0 ppm`.
  String get label => '${value.toStringAsFixed(1)} ppm';
}
