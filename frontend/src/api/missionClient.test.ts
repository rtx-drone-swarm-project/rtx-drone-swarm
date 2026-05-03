import { describe, expect, it, vi } from "vitest";
import { createMissionClient } from "./missionClient";

describe("missionClient", () => {
  it("creates, starts, and stops missions with expected requests", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "m1", status: "idle" }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "m1", status: "running" }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "m1", status: "stopped" }) });

    vi.stubGlobal("fetch", fetchMock);

    const client = createMissionClient("http://localhost:8000");

    await client.createMission({
      name: "test",
      bounds: { min_lat: 1, max_lat: 2, min_lon: 3, max_lon: 4 },
      drones: [{ id: "d1", lat: 1.5, lon: 3.5 }]
    });
    await client.startMission("m1");
    await client.stopMission("m1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/missions",
      expect.objectContaining({ method: "POST" })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/missions/m1/start",
      expect.objectContaining({ method: "POST" })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://localhost:8000/missions/m1/stop",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("sends algorithm in body when provided", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "m1", status: "running" }) });
    vi.stubGlobal("fetch", fetchMock);

    const client = createMissionClient("http://localhost:8000");
    await client.startMission("m1", "apf");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/missions/m1/start",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ algorithm: "apf" })
      })
    );
  });

  it("sends sweep algorithm in body when sweep is selected", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "m1", status: "running" }) });
    vi.stubGlobal("fetch", fetchMock);

    const client = createMissionClient("http://localhost:8000");
    await client.startMission("m1", "sweep");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/missions/m1/start",
      expect.objectContaining({ body: JSON.stringify({ algorithm: "sweep" }) })
    );
  });

  it("sends voronoi algorithm in body when voronoi is selected", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "m1", status: "running" }) });
    vi.stubGlobal("fetch", fetchMock);

    const client = createMissionClient("http://localhost:8000");
    await client.startMission("m1", "voronoi");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/missions/m1/start",
      expect.objectContaining({ body: JSON.stringify({ algorithm: "voronoi" }) })
    );
  });

  it("sends no body when algorithm is omitted", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "m1", status: "running" }) });
    vi.stubGlobal("fetch", fetchMock);

    const client = createMissionClient("http://localhost:8000");
    await client.startMission("m1");

    const callInit = fetchMock.mock.calls[0][1];
    expect(callInit.body).toBeUndefined();
  });

  it("throws backend response text on error", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, text: async () => "bad request" });
    vi.stubGlobal("fetch", fetchMock);

    const client = createMissionClient("http://localhost:8000");

    await expect(
      client.createMission({
        name: "test",
        bounds: { min_lat: 1, max_lat: 2, min_lon: 3, max_lon: 4 },
        drones: [{ id: "d1", lat: 1.5, lon: 3.5 }]
      })
    ).rejects.toThrow("bad request");
  });

  it("starts and reads benchmark runs", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ run_id: "b1", status: "running" }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ run_id: "b1", status: "complete" }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ runs: [{ run_id: "b1" }] }) });
    vi.stubGlobal("fetch", fetchMock);

    const client = createMissionClient("http://localhost:8000");
    await client.startBenchmark({
      algorithms: ["voronoi", "sweep"],
      iterations: 50,
      bounds: { min_lat: 1, max_lat: 2, min_lon: 3, max_lon: 4 },
      drone_count: 5,
      target_count: 3,
      timeout_seconds: 120
    });
    await client.getBenchmarkRun("b1");
    await client.listBenchmarkRuns();

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/benchmark",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          algorithms: ["voronoi", "sweep"],
          iterations: 50,
          bounds: { min_lat: 1, max_lat: 2, min_lon: 3, max_lon: 4 },
          drone_count: 5,
          target_count: 3,
          timeout_seconds: 120
        })
      })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(2, "http://localhost:8000/benchmark/b1", undefined);
    expect(fetchMock).toHaveBeenNthCalledWith(3, "http://localhost:8000/benchmark/runs", undefined);
  });

  it("lists discovered algorithms", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ algorithms: [{ key: "voronoi_aco", label: "Voronoi (ACO)" }] })
      });
    vi.stubGlobal("fetch", fetchMock);

    const client = createMissionClient("http://localhost:8000");
    const payload = await client.listAlgorithms();

    expect(payload.algorithms[0].key).toBe("voronoi_aco");
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/algorithms", undefined);
  });
});
