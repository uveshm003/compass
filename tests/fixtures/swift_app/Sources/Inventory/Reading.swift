// Readings from gas sensors and the rule that turns one into an alarm.
import Foundation

/// Concentration in ppm at which a reading counts as an alarm.
public let defaultThreshold: Double = 40.0

/// How serious an alarm is.
public enum Severity: String, Codable {
    case low, high
    case critical = "crit"

    /// Readings above this many ppm are critical.
    public static let criticalLevel: Double = 200.0

    /// The severity of a concentration that already counts as an alarm.
    public static func of(ppm: Double) -> Severity {
        ppm >= criticalLevel ? .critical : ppm >= defaultThreshold * 2 ? .high : .low
    }
}

/// A reading from one sensor.
public struct Reading: Codable, Equatable {
    /// The sensor's serial number.
    public let sensorId: String
    public private(set) var ppm: Double
    private var takenAt: Date

    /// Creates a reading taken now.
    public init(sensorId: String, ppm: Double) {
        self.sensorId = sensorId
        self.ppm = ppm
        self.takenAt = Date()
    }

    /// True when the reading crosses the alarm threshold.
    public func isAlarm(threshold: Double = defaultThreshold) -> Bool {
        ppm >= threshold
    }

    /// The alarm's severity, or nil when the reading is not an alarm.
    public func severity() -> Severity? {
        isAlarm() ? Severity.of(ppm: ppm) : nil
    }

    private func age(now: Date) -> TimeInterval {
        now.timeIntervalSince(takenAt)
    }
}

extension Reading: CustomStringConvertible {
    public var description: String { "\(sensorId): \(ppm) ppm" }

    /// Whether the reading is older than `seconds`.
    func isStale(after seconds: TimeInterval, now: Date = Date()) -> Bool {
        age(now: now) > seconds
    }
}
