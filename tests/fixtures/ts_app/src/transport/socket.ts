export const DEFAULT_URL = "wss://sensors.example.com/live";

export const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

// Minimal typed wrapper around WebSocket.
export class SensorSocket {
  #ws: WebSocket | null = null;

  open(url: string = DEFAULT_URL): void {
    this.#ws = new WebSocket(url);
  }

  protected onMessage(data: string): void {}

  private handle = (event: MessageEvent): void => {
    this.onMessage(String(event.data));
  };
}

function parseFrame(raw: string): unknown {
  return JSON.parse(raw);
}
