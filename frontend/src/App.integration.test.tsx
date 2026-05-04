import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const mocks = vi.hoisted(() => ({
  mapPanelProps: [] as any[]
}));

vi.mock("./components/map/MapPanel", () => ({
  default: (props: { onSelectArea: (lat: number, lon: number, bounds: any) => void }) => {
    mocks.mapPanelProps.push(props);
    return (
      <button
        type="button"
        onClick={() =>
          props.onSelectArea(33.5, -117.2, {
            min_lat: 33.45,
            max_lat: 33.55,
            min_lon: -117.25,
            max_lon: -117.15
          })
        }
      >
        Select Area
      </button>
    );
  }
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
  beforeEach(() => {
    MockWebSocket.instances = [];
    mocks.mapPanelProps = [];
  });

  it("sanitizes drone payloads during mission creation and supports mission completion flow", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);

    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "m1", status: "idle", progress: 0 }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "m1", status: "searching", progress: 0, targets: [] }) })
      .mockResolvedValue({ ok: true, json: async () => ({ algorithm: "sweep", coverage_pct: 0, targets_total: 2, targets_found: 2, found_at_seconds: [] }) });

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
      status: "search_complete",
      progress: 100,
      targets: [
        { id: "t1", lat: 33.51, lon: -117.21, status: "found" },
        { id: "t2", lat: 33.52, lon: -117.22, status: "found" }
      ]
    });

    await waitFor(() => {
      expect(screen.getByText("Search Complete - Hikers Found")).toBeTruthy();
      expect(screen.getByText("Found Hikers (2)")).toBeTruthy();
      expect(screen.getAllByText("Hiker 1").length).toBeGreaterThan(0);
      expect(screen.getAllByText("Hiker 2").length).toBeGreaterThan(0);
    });
    // await waitFor(() => {
    //   expect(screen.getAllByText("Sweep (Voronoi + Lawnmower)").length).toBeGreaterThan(1);
    // });

    fireEvent.click(
      screen.getAllByRole("button", { name: "Recall Drones" })[0]
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Start Mission" })).toBeTruthy();
    });
  });

  it("keeps accumulating drone trails across repeated running status updates", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);
    vi.stubGlobal("fetch", vi.fn());

    render(<App />);

    const socket = MockWebSocket.instances[0];
    socket.sendMessage({
      type: "mission_status",
      mission_id: "m1",
      status: "searching",
      progress: 0,
      targets: []
    });
    socket.sendMessage({
      type: "telemetry",
      drones: [{ id: "d1", lat: 33.5, lon: -117.2 }]
    });
    socket.sendMessage({
      type: "mission_status",
      mission_id: "m1",
      status: "searching",
      progress: 5,
      targets: []
    });
    socket.sendMessage({
      type: "telemetry",
      drones: [{ id: "d1", lat: 33.51, lon: -117.21 }]
    });

    await waitFor(() => {
      const latestProps = mocks.mapPanelProps[mocks.mapPanelProps.length - 1];
      expect(latestProps.droneTrails["d1"]).toEqual([[33.5, -117.2], [33.51, -117.21]]);
    });
  });
});
