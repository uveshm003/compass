# src/transport/  (3 files, 12 symbols) — Transport layer: connections, retries and backoff for the live feed
## index.ts — Transport layer: connections, retries and backoff for the live feed
## reconnect.ts
- L4  class ReconnectPolicy — Retry strategy for dropped connections
- L7    method constructor(private readonly maxDelayMs: number = 30_000)
- L10    method next(attempt: number): number — Delay in ms, exponential with jitter
- L15    method reset(): void
- L24  fn withRetry<T>(op: () => Promise<T>, policy: ReconnectPolicy): Promise<T> — Wraps an async op with retries
## socket.ts
- L1  const DEFAULT_URL = "wss://sensors.example.com/live"
- L3  fn sleep(ms: number): Promise<void>
- L6  class SensorSocket — Minimal typed wrapper around WebSocket
- L9    method open(url: string = DEFAULT_URL): void
- L13    method onMessage(data: string): void
- L15    method handle(event: MessageEvent): void
- L20  fn parseFrame(raw: string): unknown
