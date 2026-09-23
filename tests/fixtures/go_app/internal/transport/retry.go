package transport

import (
	"errors"
	"time"
)

// MaxAttempts caps retries for one frame.
const MaxAttempts = 5

const (
	minDelay = 100 * time.Millisecond
	maxDelay = 30 * time.Second
)

// ErrGiveUp is returned once MaxAttempts is exhausted.
var ErrGiveUp = errors.New("transport: giving up")

// Backoff computes delays between attempts.
type Backoff interface {
	// Next returns the delay before attempt n.
	Next(n int) time.Duration
}

// Exponential doubles the delay each attempt.
type Exponential struct {
	Base time.Duration
	Max  time.Duration
}

// Next implements Backoff.
func (e *Exponential) Next(n int) time.Duration {
	d := e.Base << n
	if d > e.Max {
		return e.Max
	}
	return d
}

func (e Exponential) String() string { return "exponential" }

// Retry calls op until it succeeds or attempts run out.
func Retry(op func() error, b Backoff) error {
	for n := 0; n < MaxAttempts; n++ {
		if err := op(); err == nil {
			return nil
		}
		time.Sleep(b.Next(n))
	}
	return ErrGiveUp
}

type queue[T any] struct {
	items []T
}

func (q *queue[T]) push(v T) { q.items = append(q.items, v) }

// Bounds for a single wait.
var MinWait, MaxWait time.Duration
