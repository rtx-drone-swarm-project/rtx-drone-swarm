import { describe, expect, it } from "vitest";
import { formatElapsed, formatSeconds, normalizeMissionStatus, statusLabel } from "./format";

describe("format utilities", () => {
  it("formats elapsed seconds", () => {
    expect(formatElapsed(0)).toBe("00:00");
    expect(formatElapsed(65)).toBe("01:05");
  });

  it("formats optional seconds", () => {
    expect(formatSeconds(undefined)).toBe("--:--");
    expect(formatSeconds(-1)).toBe("--:--");
    expect(formatSeconds(7)).toBe("00:07");
  });

  it("normalizes mission status values", () => {
    expect(normalizeMissionStatus("in_progress")).toBe("running");
    expect(normalizeMissionStatus("completed")).toBe("complete");
    expect(normalizeMissionStatus("idle")).toBe("idle");
  });

  it("returns operator label for mission status", () => {
    expect(statusLabel("running")).toBe("Mission in progress");
    expect(statusLabel("stopped")).toBe("Mission stopped");
    expect(statusLabel("complete")).toBe("Mission completed");
    expect(statusLabel("anything-else")).toBe("Idle");
  });
});
