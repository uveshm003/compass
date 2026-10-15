/* Retry with exponential backoff, shared by the C and C++ code. */
#ifndef SENSOR_RETRY_H
#define SENSOR_RETRY_H

#ifdef __cplusplus
extern "C" {
#endif

/** Attempts allowed before a sensor is marked offline. */
#define RETRY_MAX_ATTEMPTS 5

/* Clamp x between lo and hi. */
#define RETRY_CLAMP(x, lo, hi) ((x) < (lo) ? (lo) : ((x) > (hi) ? (hi) : (x)))

/** Backoff state for one sensor connection. */
typedef struct backoff {
    int attempt;
    int base_ms;
} backoff_t;

/** Outcome of one read attempt. */
typedef enum { RETRY_OK, RETRY_AGAIN, RETRY_GIVE_UP } retry_result;

typedef unsigned int millis_t;

/**
 * Delay before the next attempt, in milliseconds.
 *
 * @param b backoff state, advanced by one attempt
 */
millis_t backoff_next_delay(struct backoff *b);

/* Start counting attempts again after a good read. */
void backoff_reset(backoff_t *b);

retry_result retry_step(backoff_t *b, int ok);

#ifdef __cplusplus
}
#endif

#endif /* SENSOR_RETRY_H */
