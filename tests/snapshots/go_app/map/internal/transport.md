# internal/transport/  (3 files, 15 symbols) — Package transport moves sensor frames between devices and the backend
## doc.go — Package transport moves sensor frames between devices and the backend
## retry.go
- L9  const MaxAttempts = 5 — MaxAttempts caps retries for one frame
- L12  const minDelay = 100 * time.Millisecond
- L13  const maxDelay = 30 * time.Second
- L17  var ErrGiveUp = errors.New("transport: giving up") — ErrGiveUp is returned once MaxAttempts is exhausted
- L20  interface Backoff — Backoff computes delays between attempts
- L22    method Next(n int) time.Duration — Next returns the delay before attempt n
- L26  struct Exponential — Exponential doubles the delay each attempt
- L32  method Exponential.Next(n int) time.Duration — Next implements Backoff
- L40  method Exponential.String() string
- L43  fn Retry(op func() error, b Backoff) error — Retry calls op until it succeeds or attempts run out
- L53  struct queue[T any]
- L57  method queue.push(v T)
- L60  var MinWait, MaxWait time.Duration — Bounds for a single wait
## retry_test.go
- L5  fn TestRetry(t *testing.T)
