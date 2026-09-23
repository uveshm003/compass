# src/  (2 files, 15 symbols) — Sensor gateway: collects readings and forwards them upstream
## lib.rs — Sensor gateway: collects readings and forwards them upstream
- L8  const MAX_FRAME: usize = 4096 — Maximum frame size in bytes
- L11  struct Reading — A reading from one sensor
- L17  impl Reading
- L19    method new(sensor: impl Into<String>, ppm: f64) -> Self — Creates a reading
- L23    method validate(&self) -> bool
- L28  impl fmt::Display for Reading
- L29    method fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result
- L34  enum State
- L40  trait Sink — Something that can ship readings
- L42    method send(&mut self, reading: &Reading) -> anyhow::Result<()> — Sends one reading
- L44    method flush(&mut self) -> anyhow::Result<()>
- L49  type Result<T> = std::result::Result<T, Error>
- L51  struct Error
- L54  macro ensure_positive
## main.rs
- L3  fn main()
