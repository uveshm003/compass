#include "sensors/alarm.hpp"

#include <fmt/core.h>

namespace sensors {
namespace {

// Label used in log lines.
const char* label(Level level)
{
    switch (level) {
    case Level::Warn:
        return "warn";
    case Level::Alarm:
        return "alarm";
    default:
        return "ok";
    }
}

}  // namespace

bool Reading::is_alarm(double threshold) const
{
    return ppm >= threshold;
}

AlarmMonitor::AlarmMonitor(double threshold) : threshold_(threshold) {}

Level AlarmMonitor::classify(const Reading& reading)
{
    if (reading.is_alarm(threshold_)) {
        record(Level::Alarm);
        on_alarm(reading);
        return Level::Alarm;
    }
    return reading.ppm >= threshold_ / 2 ? Level::Warn : Level::Ok;
}

void AlarmMonitor::on_alarm(const Reading& reading)
{
    fmt::print("{} {} at {} ppm\n", label(Level::Alarm), reading.sensor, reading.ppm);
}

void AlarmMonitor::record(Level level)
{
    if (level == Level::Alarm) {
        ++alarms_;
    }
}

}  // namespace sensors
