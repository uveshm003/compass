import 'package:sensor_kit/sensor_kit.dart';
import 'package:test/test.dart';

void main() {
  test('a reading over the threshold is an alarm', () {
    expect(Reading('s1', 75).isAlarm(), isTrue);
  });

  test('parse reads the id and the value', () {
    final reading = Reading.parse('s2:12.5');
    expect(reading.sensorId, 's2');
    expect(reading.value, 12.5);
  });

  group('classify', () {
    test('is critical at twice the threshold', () {
      expect(classify(const Reading('s3', 101), 50), AlarmLevel.critical);
    });
  });
}
