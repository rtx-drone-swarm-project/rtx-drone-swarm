import { describe, expect, it } from "vitest";
import { formatElapsed, formatSeconds, statusLabel } from "./format";

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

  it("returns operator label for mission status", () => {
    expect(statusLabel("searching")).toBe("Searching");
    expect(statusLabel("search_complete")).toBe("Search completed");
    expect(statusLabel("paused")).toBe("Paused");
    expect(statusLabel("mission_complete")).toBe("Mission completed");
    expect(statusLabel("anything-else")).toBe("Idle");
  });
});
