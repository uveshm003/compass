using Microsoft.Extensions.Logging.Abstractions;
using Sensors.Core.Alarms;
using Sensors.Core.Models;
using Xunit;

namespace Sensors.Core.Tests;

public class AlarmEvaluatorTests
{
    private readonly AlarmEvaluator _evaluator = new(NullLogger<AlarmEvaluator>.Instance);

    [Fact]
    public void Classify_ReturnsCriticalAboveTwiceTheThreshold()
    {
        Assert.Equal(AlarmLevel.Critical, _evaluator.Classify(new Reading("gx-1", 120.0)));
    }

    [Fact]
    public void Classify_ReturnsNormalBelowTheThreshold()
    {
        Assert.Equal(AlarmLevel.Normal, _evaluator.Classify(new Reading("gx-1", 12.5)));
    }
}
