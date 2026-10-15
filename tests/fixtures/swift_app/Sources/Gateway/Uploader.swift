import Foundation
import Inventory

/// Sends pending readings upstream, retrying with backoff.
actor Uploader {
    private let store: ReadingStore
    private var backoff = Backoff()

    init(store: ReadingStore) {
        self.store = store
    }

    /// Uploads every pending reading; returns how many were sent.
    func flush(send: (Reading) async throws -> Void) async -> Int {
        var sent = 0
        for reading in store.pending() {
            while true {
                do {
                    try await send(reading)
                    sent += 1
                    break
                } catch {
                    guard backoff.shouldRetry() else { return sent }
                    try? await Task.sleep(nanoseconds: UInt64(backoff.nextDelay() * 1e9))
                }
            }
        }
        return sent
    }
}
