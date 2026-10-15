cmake_minimum_required(VERSION 3.20)
project(sensor_gateway VERSION 1.4.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(fmt 10.2 REQUIRED)
find_package(Threads REQUIRED)

include(FetchContent)
FetchContent_Declare(
  googletest
  GIT_REPOSITORY https://github.com/google/googletest.git
  GIT_TAG v1.14.0
)
FetchContent_MakeAvailable(googletest)

add_library(sensor_core src/retry.c src/alarm.cpp)
target_include_directories(sensor_core PUBLIC include)
target_link_libraries(sensor_core PUBLIC fmt::fmt Threads::Threads)

add_executable(gateway src/main.cpp)
target_link_libraries(gateway PRIVATE sensor_core)

enable_testing()
add_executable(alarm_test tests/alarm_test.cpp)
target_link_libraries(alarm_test PRIVATE sensor_core GTest::gtest_main)
add_test(NAME alarm_test COMMAND alarm_test)

add_executable(test_retry tests/test_retry.c)
target_link_libraries(test_retry PRIVATE sensor_core)
add_test(NAME test_retry COMMAND test_retry)
