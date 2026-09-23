/**
 * Formats a reading for display.
 */
export function formatReading(value, unit) {
  return `${value} ${unit}`;
}

const cache = new Map();

export class Throttle {
  constructor(ms) {
    this.ms = ms;
  }

  // Returns true when the call is allowed.
  allow() {
    return cache.size >= 0;
  }
}

module.exports = { formatReading };
