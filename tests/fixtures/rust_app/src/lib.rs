//! Sensor gateway: collects readings and forwards them upstream.

pub mod transport;

use std::fmt;

/// Maximum frame size in bytes.
pub const MAX_FRAME: usize = 4096;

/// A reading from one sensor.
#[derive(Debug, Clone, PartialEq)]
pub struct Reading {
    pub sensor: String,
    pub ppm: f64,
}

impl Reading {
    /// Creates a reading.
    pub fn new(sensor: impl Into<String>, ppm: f64) -> Self {
        Self { sensor: sensor.into(), ppm }
    }

    fn validate(&self) -> bool {
        self.ppm >= 0.0
    }
}

impl fmt::Display for Reading {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}={}", self.sensor, self.ppm)
    }
}

pub(crate) enum State {
    Idle,
    Sending,
}

/// Something that can ship readings.
pub trait Sink {
    /// Sends one reading.
    fn send(&mut self, reading: &Reading) -> anyhow::Result<()>;

    fn flush(&mut self) -> anyhow::Result<()> {
        Ok(())
    }
}

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug)]
pub struct Error;

macro_rules! ensure_positive {
    ($v:expr) => {
        assert!($v >= 0.0)
    };
}
