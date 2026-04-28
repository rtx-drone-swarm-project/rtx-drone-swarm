import { describe, expect, it, vi } from "vitest";
import { createMissionClient } from "./missionClient";

describe("missionClient", () => {
  it("creates, starts, and stops missions with expected requests", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "m1", status: "idle" }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "m1", status: "searching" }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "m1", status: "paused" }) });

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
});
