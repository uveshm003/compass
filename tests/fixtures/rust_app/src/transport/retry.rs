use std::time::Duration;

/// Exponential backoff with a cap.
#[derive(Debug, Default)]
pub struct Backoff {
    attempt: u32,
}

impl Backoff {
    /// Delay before the next attempt.
    pub fn next_delay(&mut self) -> Duration {
        self.attempt += 1;
        Duration::from_millis(100 * 2u64.pow(self.attempt.min(8)))
    }
}

pub mod policy {
    /// Retries allowed before giving up.
    pub static MAX_RETRIES: u32 = 5;

    pub fn should_retry(attempt: u32) -> bool {
        attempt < MAX_RETRIES
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn delay_grows() {
        let mut backoff = Backoff::default();
        assert!(backoff.next_delay() < backoff.next_delay());
    }
}
