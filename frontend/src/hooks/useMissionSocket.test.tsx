import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import useMissionSocket from "./useMissionSocket";

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;

  constructor(_url: string) {
    MockWebSocket.instances.push(this);
  }

  close() {
    this.onclose?.();
  }
}

describe("useMissionSocket", () => {
  it("dispatches typed websocket messages", () => {
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);

    const onConnectedChange = vi.fn();
    const onTelemetry = vi.fn();
    const onMissionStatus = vi.fn();
    const onMissionProgress = vi.fn();
    const onTargetFound = vi.fn();
    const onBenchmarkProgress = vi.fn();

    function Harness() {
      useMissionSocket({
        apiPort: "8000",
        onConnectedChange,
        onTelemetry,
        onMissionStatus,
        onMissionProgress,
        onTargetFound,
        onBenchmarkProgress
      });
      return null;
    }

    render(<Harness />);

    const socket = MockWebSocket.instances[0];
    socket.onopen?.();

    socket.onmessage?.({ data: JSON.stringify({ type: "telemetry", drones: [{ id: "d1", lat: 1, lon: 2 }] }) });
    socket.onmessage?.({ data: JSON.stringify({ type: "mission_status", status: "running", mission_id: "m1" }) });
    socket.onmessage?.({ data: JSON.stringify({ type: "mission_progress", progress: 42 }) });
    socket.onmessage?.({ data: JSON.stringify({ type: "target_found", target_id: "t1", lat: 1, lon: 2 }) });
    socket.onmessage?.({ data: JSON.stringify({ type: "benchmark_progress", run_id: "b1", completed: 1, total: 3 }) });

    expect(onConnectedChange).toHaveBeenCalledWith(true);
    expect(onTelemetry).toHaveBeenCalledTimes(1);
    expect(onMissionStatus).toHaveBeenCalledTimes(1);
    expect(onMissionProgress).toHaveBeenCalledTimes(1);
    expect(onTargetFound).toHaveBeenCalledTimes(1);
    expect(onBenchmarkProgress).toHaveBeenCalledTimes(1);
  });
});
