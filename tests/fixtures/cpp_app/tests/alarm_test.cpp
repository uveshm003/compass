#include <gtest/gtest.h>

#include "sensors/alarm.hpp"

TEST(AlarmMonitor, ClassifiesAlarm)
{
    sensors::AlarmMonitor monitor(50.0);
    EXPECT_EQ(monitor.classify({"s1", 62.5}), sensors::Level::Alarm);
    EXPECT_EQ(monitor.alarms(), 1);
}

TEST(Reading, IsAlarm)
{
    sensors::Reading reading{"s1", 50.0};
    EXPECT_TRUE(reading.is_alarm());
}
