// Gateway entry point: polls the sensors and reports alarms.
#include <chrono>
#include <thread>

#include "retry.h"
#include "sensors/alarm.hpp"

int main()
{
    sensors::AlarmMonitor monitor(sensors::kDefaultThreshold);
    backoff_t backoff = {0, 100};
    sensors::Reading reading{"s1", 62.5};
    if (monitor.classify(reading) == sensors::Level::Alarm) {
        millis_t wait = backoff_next_delay(&backoff);
        std::this_thread::sleep_for(std::chrono::milliseconds(wait));
    }
    return monitor.alarms() > 0 ? 1 : 0;
}
