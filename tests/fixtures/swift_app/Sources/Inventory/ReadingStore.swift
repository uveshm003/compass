import Foundation
import Logging

/**
 * Somewhere readings are kept until they are uploaded.
 */
public protocol ReadingStore {
    /// Keeps one reading.
    func save(_ reading: Reading) throws
    /// Readings not yet uploaded, oldest first.
    func pending() -> [Reading]
}

/// A store that keeps readings in memory; used by tests and the simulator.
public final class MemoryStore: ReadingStore {
    private var readings: [Reading] = []
    private let logger = Logger(label: "inventory.store")

    public init() {}

    public func save(_ reading: Reading) throws {
        if reading.isAlarm() {
            logger.warning("alarm from \(reading.sensorId)")
        }
        readings.append(reading)
    }

    public func pending() -> [Reading] {
        readings
    }
}
