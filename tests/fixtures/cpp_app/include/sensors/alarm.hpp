// Alarm thresholds and the monitor that applies them.
#pragma once

#include <string>

#include "retry.h"

namespace sensors {

/// Severity of a reading against its threshold.
enum class Level { Ok, Warn, Alarm };

/// Default alarm threshold, in ppm.
constexpr double kDefaultThreshold = 50.0;

/** A reading from one gas sensor. */
struct Reading {
    std::string sensor;
    double ppm = 0.0;

    /// True when the reading crosses the alarm threshold.
    bool is_alarm(double threshold = kDefaultThreshold) const;
};

/// Watches readings and counts the alarms they raise.
class AlarmMonitor {
public:
    explicit AlarmMonitor(double threshold);

    /// Classify a reading and record any alarm.
    Level classify(const Reading& reading);

    /// Alarms raised so far.
    int alarms() const { return alarms_; }

protected:
    virtual void on_alarm(const Reading& reading);

private:
    void record(Level level);

    double threshold_;
    int alarms_ = 0;
};

template <typename T>
T clamp_ppm(T value, T limit)
{
    return value > limit ? limit : value;
}

}  // namespace sensors
