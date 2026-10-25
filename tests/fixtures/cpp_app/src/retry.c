#include "retry.h"

#include <stddef.h>

/* Upper bound for a single delay. */
static const millis_t max_delay_ms = 30000;

static millis_t clamp_delay(millis_t delay);

/* Never wait longer than max_delay_ms. */
static millis_t clamp_delay(millis_t delay)
{
    return RETRY_CLAMP(delay, 0, max_delay_ms);
}

millis_t backoff_next_delay(struct backoff *b)
{
    b->attempt += 1;
    return clamp_delay((millis_t)b->base_ms << b->attempt);
}

void backoff_reset(backoff_t *b)
{
    if (b != NULL) {
        b->attempt = 0;
    }
}

retry_result retry_step(backoff_t *b, int ok)
{
    if (ok) {
        backoff_reset(b);
        return RETRY_OK;
    }
    return b->attempt + 1 >= RETRY_MAX_ATTEMPTS ? RETRY_GIVE_UP : RETRY_AGAIN;
}
