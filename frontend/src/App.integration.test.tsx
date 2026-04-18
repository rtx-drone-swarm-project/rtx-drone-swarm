import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./components/map/MapPanel", () => ({
  default: ({ onSelectArea }: { onSelectArea: (lat: number, lon: number, bounds: any) => void }) => (
    <button
      type="button"
      onClick={() =>
        onSelectArea(33.5, -117.2, {
          min_lat: 33.45,
          max_lat: 33.55,
          min_lon: -117.25,
          max_lon: -117.15
        })
      }
    >
      Select Area
    </button>
  )
}));

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

  sendMessage(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

describe("App integration", () => {
  it("sanitizes drone payloads during mission creation and supports mission completion flow", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "m1", status: "idle", progress: 0 }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "m1", status: "running", progress: 0, targets: [] }) });

    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    const socket = MockWebSocket.instances[0];
    socket.sendMessage({
      type: "telemetry",
      drones: [
        {
          id: "7",
          sysid: 7,
          lat: 33.51,
          lon: -117.21,
          alt: 120,
          heading: 42,
          groundspeed: 14.5,
          target_lat: 33.515,
          target_lon: -117.205,
          role: "finder",
          status: null,
          mode: null,
          telemetry_source: null,
          armed: null
        }
      ]
    });

    fireEvent.click(screen.getByRole("button", { name: "Select Area" }));
    fireEvent.click(screen.getByRole("button", { name: "Start Mission" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    const createMissionRequest = fetchMock.mock.calls[0];
    const init = createMissionRequest[1] as RequestInit;
    const body = JSON.parse(String(init.body));

    expect(body.drones).toEqual([
      {
        id: "7",
        sysid: 7,
        lat: 33.51,
        lon: -117.21,
        alt: 120,
        heading: 42,
        groundspeed: 14.5,
        target_lat: 33.515,
        target_lon: -117.205,
        role: "finder"
      }
    ]);

    expect(body.drones[0]).not.toHaveProperty("status");
    expect(body.drones[0]).not.toHaveProperty("mode");
    expect(body.drones[0]).not.toHaveProperty("telemetry_source");
    expect(body.drones[0]).not.toHaveProperty("armed");

    socket.sendMessage({
      type: "mission_status",
      mission_id: "m1",
      status: "complete",
      progress: 100,
      targets: [
        { id: "t1", lat: 33.51, lon: -117.21, status: "found" },
        { id: "t2", lat: 33.52, lon: -117.22, status: "found" }
      ]
    });

    await waitFor(() => {
      expect(screen.getByText("Mission Complete")).toBeTruthy();
      expect(screen.getByText("Mission Complete - Hikers Found")).toBeTruthy();
      expect(screen.getByText("Found Hikers (2)")).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: "Reset Mission" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Start Mission" })).toBeTruthy();
    });
  });
});
