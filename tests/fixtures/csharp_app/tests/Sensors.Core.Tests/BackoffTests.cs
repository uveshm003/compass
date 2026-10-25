using Sensors.Core.Transport;
using Xunit;

namespace Sensors.Core.Tests;

public class BackoffTests
{
    [Fact]
    public void NextDelay_GrowsUntilTheCap()
    {
        var backoff = new Backoff(TimeSpan.FromSeconds(1));
        Assert.True(backoff.NextDelay(2) > backoff.NextDelay(1));
        Assert.Equal(TimeSpan.FromSeconds(1), backoff.NextDelay(12));
    }

    [Theory]
    [InlineData(1, true)]
    [InlineData(5, false)]
    public void ShouldRetry_StopsAtMaxAttempts(int attempt, bool expected)
    {
        Assert.Equal(expected, new Backoff(TimeSpan.FromSeconds(1)).ShouldRetry(attempt));
    }
}
