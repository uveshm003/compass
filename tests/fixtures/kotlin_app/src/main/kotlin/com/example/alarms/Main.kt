package com.example.alarms

import com.example.alarms.transport.Backoff
import com.example.alarms.transport.retry
import kotlinx.coroutines.runBlocking

/** Reads one "sensor,ppm" line from the arguments and notifies on an alarm. */
fun main(args: Array<String>) = runBlocking {
    val reading = Reading.parse(args.first())
    if (listOf(reading).alarms().isNotEmpty()) {
        retry(Backoff()) { ConsoleNotifier.notify(reading, reading.level()) }
    }
}
