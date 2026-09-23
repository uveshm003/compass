# src/transport/  (2 files, 8 symbols) — Transport: framing and retries for the upstream link
## mod.rs — Transport: framing and retries for the upstream link
## retry.rs
- L4  struct Backoff — Exponential backoff with a cap
- L9  impl Backoff
- L11    method next_delay(&mut self) -> Duration — Delay before the next attempt
- L17  module policy
- L19    const MAX_RETRIES: u32 = 5 — Retries allowed before giving up
- L21    fn should_retry(attempt: u32) -> bool
- L26  module tests
- L30    fn delay_grows()
