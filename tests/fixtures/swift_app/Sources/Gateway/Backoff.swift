import Foundation

/// Retries allowed before an upload gives up.
let maxRetries = 5

/// Exponential backoff with a cap, for retrying uploads.
struct Backoff {
    private var attempt = 0

    /// Seconds to wait before the next attempt.
    mutating func nextDelay() -> TimeInterval {
        attempt += 1
        return min(pow(2.0, Double(attempt)) * 0.1, 30)
    }

    /// Whether another attempt is allowed.
    func shouldRetry() -> Bool {
        attempt < maxRetries
    }
}
