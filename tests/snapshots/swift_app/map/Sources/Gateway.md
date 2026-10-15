# Sources/Gateway/  (3 files, 9 symbols)
## Backoff.swift
- L4  const maxRetries = 5 — Retries allowed before an upload gives up
- L7  struct Backoff — Exponential backoff with a cap, for retrying uploads
- L11    method nextDelay() -> TimeInterval — Seconds to wait before the next attempt
- L17    method shouldRetry() -> Bool — Whether another attempt is allowed
## Uploader.swift
- L5  class Uploader — Sends pending readings upstream, retrying with backoff
- L9    method init(store: ReadingStore)
- L14    method flush(send: (Reading) async throws -> Void) async -> Int — Uploads every pending reading; returns how many were sent
## main.swift — The gateway: reads sensors once, then uploads what it collected
- L5  struct Gateway: AsyncParsableCommand
- L9    method run() async throws
