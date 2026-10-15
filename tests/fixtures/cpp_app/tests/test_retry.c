#include <assert.h>

#include "retry.h"

static void test_delay_grows(void)
{
    backoff_t b = {0, 100};
    millis_t first = backoff_next_delay(&b);
    assert(backoff_next_delay(&b) > first);
}

static void test_gives_up(void)
{
    backoff_t b = {RETRY_MAX_ATTEMPTS, 100};
    assert(retry_step(&b, 0) == RETRY_GIVE_UP);
}

int main(void)
{
    test_delay_grows();
    test_gives_up();
    return 0;
}
