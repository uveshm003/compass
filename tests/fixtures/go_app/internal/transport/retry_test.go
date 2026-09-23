package transport

import "testing"

func TestRetry(t *testing.T) {
	calls := 0
	err := Retry(func() error { calls++; return nil }, &Exponential{})
	if err != nil || calls != 1 {
		t.Fatal(err)
	}
}
