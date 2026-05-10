import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ActionsPanel from "./ActionsPanel";
import type { MissionStatus } from "../../types/ws";

function renderPanel(overrides: Partial<React.ComponentProps<typeof ActionsPanel>> = {}) {
  const defaults = {
    selectedBounds: {
      min_lat: 33.45,
      max_lat: 33.55,
      min_lon: -117.25,
      max_lon: -117.15
    },
    missionStatus: "idle" as MissionStatus,
    missionActive: false,
    missionLocked: false,
    validDroneCount: 15,
    mission: null,
    selectedAlgorithm: "voronoi" as const,
    onAlgorithmChange: vi.fn(),
    onStartMission: vi.fn(),
    onStopMission: vi.fn(),
    onRecallDrones: vi.fn(),
    onResetMission: vi.fn()
  };

  return render(<ActionsPanel {...defaults} {...overrides} />);
}

describe("ActionsPanel", () => {
  it("keeps reset available after a mission is paused", () => {
    renderPanel({
      missionStatus: "paused",
      missionActive: true,
      mission: { id: "m1", status: "paused" }
    });

    const resetButton = screen.getByRole("button", { name: "Reset Mission" }) as HTMLButtonElement;
    expect(resetButton.disabled).toBe(false);
  });

  it("keeps reset available when search is complete", () => {
    renderPanel({
      missionStatus: "search_complete",
      missionActive: true,
      mission: { id: "m1", status: "search_complete" }
    });

    const resetButton = screen.getByRole("button", { name: "Reset Mission" }) as HTMLButtonElement;
    expect(resetButton.disabled).toBe(false);
  });

  it("disables reset while a mission is actively moving", () => {
    renderPanel({
      missionStatus: "searching",
      missionActive: true,
      mission: { id: "m1", status: "searching" }
    });

    const resetButton = screen.getByRole("button", { name: "Reset Mission" }) as HTMLButtonElement;
    expect(resetButton.disabled).toBe(true);
  });
});
