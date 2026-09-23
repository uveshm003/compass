import { describe, expect, it } from "vitest";
import { ReconnectPolicy, withRetry } from "./reconnect";

describe("ReconnectPolicy", () => {
  it("caps the delay", () => {
    const policy = new ReconnectPolicy(1_000);
    expect(policy.next(20)).toBeLessThanOrEqual(1_000);
  });

  it("retries until the op succeeds", async () => {
    let calls = 0;
    const result = await withRetry(async () => (++calls < 3 ? Promise.reject(new Error("x")) : "ok"), new ReconnectPolicy(1));
    expect(result).toBe("ok");
  });
});
