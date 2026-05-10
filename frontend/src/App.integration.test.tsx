import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const mocks = vi.hoisted(() => ({
  mapPanelProps: [] as any[]
}));

vi.mock("./components/map/MapPanel", () => ({
  default: (props: {
    onSelectArea: (lat: number, lon: number, bounds: any) => void;
    onPlaceHiker?: (lat: number, lon: number) => void;
  }) => {
    mocks.mapPanelProps.push(props);
    return (
      <>
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
        <button type="button" onClick={() => props.onPlaceHiker?.(33.5, -117.2)}>
          Place Hiker On Map
        </button>
      </>
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

    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/benchmark/runs")) {
        return Promise.resolve({ ok: true, json: async () => ({ runs: [] }) });
      }
      if (url.endsWith("/missions")) {
        return Promise.resolve({ ok: true, json: async () => ({ id: "m1", status: "idle", progress: 0 }) });
      }
      if (url.endsWith("/missions/m1/start")) {
        return Promise.resolve({ ok: true, json: async () => ({ id: "m1", status: "running", progress: 0, targets: [] }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({ algorithm: "sweep", coverage_pct: 0, targets_total: 2, targets_found: 2, found_at_seconds: [] }) });
    });

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
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/missions/m1/start"))).toBe(true);
    });

    const createMissionRequest = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/missions"));
    expect(createMissionRequest).toBeTruthy();
    if (!createMissionRequest) throw new Error("missing create mission request");
    const init = createMissionRequest[1];
    expect(init).toBeTruthy();
    if (!init) throw new Error("missing create mission init");
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

    const summaryDialog = screen.getByRole("dialog", { name: "Search summary" });
    fireEvent.click(within(summaryDialog).getByRole("button", { name: "Recall Drones" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "http://localhost:8000/missions/m1/recall",
        expect.objectContaining({ method: "POST" })
      );
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

  it("sends manually placed hikers when starting a mission", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);

    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/benchmark/runs")) {
        return Promise.resolve({ ok: true, json: async () => ({ runs: [] }) });
      }
      if (url.endsWith("/missions")) {
        return Promise.resolve({ ok: true, json: async () => ({ id: "m2", status: "idle", progress: 0 }) });
      }
      if (url.endsWith("/missions/m2/start")) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            id: "m2",
            status: "searching",
            progress: 0,
            targets: [{ id: "hiker-1", lat: 33.5, lon: -117.2, status: "wandering", movement: "moving" }]
          })
        });
      }
      return Promise.resolve({ ok: true, json: async () => ({ algorithms: [] }) });
    });

    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Select Area" }));
    fireEvent.click(screen.getByRole("button", { name: "Add Hiker" }));
    expect(screen.queryByRole("button", { name: "Moving" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Place Hiker On Map" }));
    fireEvent.click(screen.getByText("Hiker 1"));
    fireEvent.click(screen.getByRole("button", { name: "Moving" }));
    fireEvent.click(screen.getByRole("button", { name: "Start Mission" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/missions/m2/start"))).toBe(true);
    });

    const createMissionRequest = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/missions"));
    expect(createMissionRequest).toBeTruthy();
    if (!createMissionRequest) throw new Error("missing create mission request");
    const body = JSON.parse(String(createMissionRequest[1]?.body));

    expect(body.hikers).toEqual([
      {
        id: "hiker-1",
        lat: 33.5,
        lon: -117.2,
        found: false,
        movement: "moving"
      }
    ]);
  });

  it("restarts hiker numbering after clearing all hikers", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);

    const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/benchmark/runs")) {
        return Promise.resolve({ ok: true, json: async () => ({ runs: [] }) });
      }
      if (url.endsWith("/missions")) {
        return Promise.resolve({ ok: true, json: async () => ({ id: "m-clear", status: "idle", progress: 0 }) });
      }
      if (url.endsWith("/missions/m-clear/start")) {
        return Promise.resolve({ ok: true, json: async () => ({ id: "m-clear", status: "searching", progress: 0, targets: [] }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({ algorithms: [] }) });
    });

    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Select Area" }));
    fireEvent.click(screen.getByRole("button", { name: "Add Hiker" }));
    fireEvent.click(screen.getByRole("button", { name: "Place Hiker On Map" }));
    fireEvent.click(screen.getByRole("button", { name: "Place Hiker On Map" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear All Hikers" }));
    fireEvent.click(screen.getByRole("button", { name: "Add Hiker" }));
    fireEvent.click(screen.getByRole("button", { name: "Place Hiker On Map" }));
    fireEvent.click(screen.getByRole("button", { name: "Start Mission" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/missions/m-clear/start"))).toBe(true);
    });

    const createMissionRequest = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/missions"));
    expect(createMissionRequest).toBeTruthy();
    if (!createMissionRequest) throw new Error("missing create mission request");
    const body = JSON.parse(String(createMissionRequest[1]?.body));

    expect(body.hikers).toEqual([
      {
        id: "hiker-1",
        lat: 33.5,
        lon: -117.2,
        found: false,
        movement: "stationary"
      }
    ]);
  });

  it("restarts hiker numbering after resetting the mission", async () => {
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);

    let missionNumber = 0;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/benchmark/runs")) {
        return Promise.resolve({ ok: true, json: async () => ({ runs: [] }) });
      }
      if (url.endsWith("/missions") && init?.method === "POST") {
        missionNumber += 1;
        return Promise.resolve({ ok: true, json: async () => ({ id: `m-reset-${missionNumber}`, status: "idle", progress: 0 }) });
      }
      if (url.endsWith("/missions/m-reset-1/start")) {
        return Promise.resolve({ ok: true, json: async () => ({ id: "m-reset-1", status: "searching", progress: 0, targets: [] }) });
      }
      if (url.endsWith("/missions/m-reset-1/stop")) {
        return Promise.resolve({ ok: true, json: async () => ({ id: "m-reset-1", status: "paused", progress: 0, targets: [] }) });
      }
      if (url.endsWith("/missions/m-reset-1") && init?.method === "DELETE") {
        return Promise.resolve({ ok: true, json: async () => ({}) });
      }
      if (url.endsWith("/missions/m-reset-2/start")) {
        return Promise.resolve({ ok: true, json: async () => ({ id: "m-reset-2", status: "searching", progress: 0, targets: [] }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({ algorithms: [] }) });
    });

    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    fireEvent.click(screen.getByRole("button", { name: "Select Area" }));
    fireEvent.click(screen.getByRole("button", { name: "Add Hiker" }));
    fireEvent.click(screen.getByRole("button", { name: "Place Hiker On Map" }));
    fireEvent.click(screen.getByRole("button", { name: "Place Hiker On Map" }));
    fireEvent.click(screen.getByRole("button", { name: "Start Mission" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/missions/m-reset-1/start"))).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "Stop Mission" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/missions/m-reset-1/stop"))).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "Reset Mission" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url, init]) => String(url).endsWith("/missions/m-reset-1") && init?.method === "DELETE")).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "Add Hiker" }));
    fireEvent.click(screen.getByRole("button", { name: "Place Hiker On Map" }));
    fireEvent.click(screen.getByRole("button", { name: "Start Mission" }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith("/missions/m-reset-2/start"))).toBe(true);
    });

    const createMissionRequests = fetchMock.mock.calls.filter(([url, init]) => String(url).endsWith("/missions") && init?.method === "POST");
    const secondBody = JSON.parse(String(createMissionRequests[1][1]?.body));

    expect(secondBody.hikers).toEqual([
      {
        id: "hiker-1",
        lat: 33.5,
        lon: -117.2,
        found: false,
        movement: "stationary"
      }
    ]);
  });
});
