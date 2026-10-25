# tests/Sensors.Core.Tests/  (3 files, 8 symbols)
## AlarmEvaluatorTests.cs
- L6  namespace Sensors.Core.Tests
- L8  class AlarmEvaluatorTests
- L12    method void Classify_ReturnsCriticalAboveTwiceTheThreshold()
- L18    method void Classify_ReturnsNormalBelowTheThreshold()
## BackoffTests.cs
- L4  namespace Sensors.Core.Tests
- L6  class BackoffTests
- L8    method void NextDelay_GrowsUntilTheCap()
- L16    method void ShouldRetry_StopsAtMaxAttempts(int attempt, bool expected)
## Sensors.Core.Tests.csproj
