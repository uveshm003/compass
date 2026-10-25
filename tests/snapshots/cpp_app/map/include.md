# include/  (1 file, 8 symbols)
## retry.h — Retry with exponential backoff, shared by the C and C++ code
- L10  macro RETRY_MAX_ATTEMPTS 5 — Attempts allowed before a sensor is marked offline
- L13  macro RETRY_CLAMP(x, lo, hi) — Clamp x between lo and hi
- L16  struct backoff_t — Backoff state for one sensor connection
- L22  enum retry_result — Outcome of one read attempt
- L24  type millis_t
- L31  fn millis_t backoff_next_delay(struct backoff *b) — Delay before the next attempt, in milliseconds
- L34  fn void backoff_reset(backoff_t *b) — Start counting attempts again after a good read
- L36  fn retry_result retry_step(backoff_t *b, int ok)
