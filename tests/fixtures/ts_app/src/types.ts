/** A gas reading as sent by the backend. */
export interface Reading {
  sensorId: string;
  ppm: number;
  /** Seconds since the epoch. */
  at(): number;
}

export type SensorId = string;

export enum Severity {
  Ok,
  Warn,
  Alarm,
}

export namespace Thresholds {
  export const METHANE = 1000;

  export function forGas(gas: string): number {
    return gas === "methane" ? METHANE : 50;
  }
}
