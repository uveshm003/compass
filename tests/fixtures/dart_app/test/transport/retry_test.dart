import 'dart:math';

import 'package:sensor_kit/src/transport/retry.dart';
import 'package:test/test.dart';

void main() {
  test('backoff stays under its cap', () {
    final backoff = Backoff(base: const Duration(milliseconds: 10), random: Random(1));
    for (var i = 1; i <= 3; i++) {
      expect(backoff.next().inMilliseconds, lessThanOrEqualTo(10 << i));
    }
    expect(backoff.entries, hasLength(3));
  });

  test('shouldRetry stops at maxAttempts', () {
    expect(shouldRetry(maxAttempts - 1), isTrue);
    expect(shouldRetry(maxAttempts), isFalse);
  });
}
