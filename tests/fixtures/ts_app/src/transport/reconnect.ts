import { sleep } from "./socket";

/** Retry strategy for dropped connections. */
export class ReconnectPolicy {
  private attempts = 0;

  constructor(private readonly maxDelayMs: number = 30_000) {}

  /** Delay in ms, exponential with jitter. */
  next(attempt: number): number {
    const base = Math.min(this.maxDelayMs, 2 ** attempt * 100);
    return base / 2 + Math.random() * (base / 2);
  }

  reset(): void {
    this.attempts = 0;
  }
}

/**
 * Wraps an async op with retries.
 * @param op the operation to retry
 */
export async function withRetry<T>(op: () => Promise<T>, policy: ReconnectPolicy): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await op();
    } catch (err) {
      await sleep(policy.next(attempt));
    }
  }
}
