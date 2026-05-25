import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ActionsPanel from "./ActionsPanel";
import { DEFAULT_ALGORITHM_OPTIONS } from "../../types/mission";
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
    setupStage: "search_area" as const,
    canStartMission: true,
    startMissionHelperText: null,
    selectedAlgorithm: "voronoi" as const,
    algorithmOptions: DEFAULT_ALGORITHM_OPTIONS,
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

  it("enables start with only a selected search area", () => {
    renderPanel({
      mission: {
        id: "m1",
        status: "idle",
        search_area_confirmed: true,
        probability_grid_confirmed: false,
      },
      startMissionHelperText: "Optional: configure a probability map before starting if you want weighted search behavior.",
    });

    const startButton = screen.getByRole("button", { name: "Start Mission" }) as HTMLButtonElement;
    expect(startButton.disabled).toBe(false);
    expect(screen.getByText("Optional: configure a probability map before starting if you want weighted search behavior.")).toBeTruthy();
  });

  it("keeps start enabled after the probability map is confirmed", () => {
    renderPanel({
      mission: {
        id: "m1",
        status: "idle",
        search_area_confirmed: true,
        probability_grid_confirmed: true,
      },
    });

    const startButton = screen.getByRole("button", { name: "Start Mission" }) as HTMLButtonElement;
    expect(startButton.disabled).toBe(false);
  });

  it("disables start during region labelling", () => {
    renderPanel({
      setupStage: "label_regions",
      canStartMission: false,
      startMissionHelperText: "Finish or go back from probability-map setup before starting.",
    });

    const startButton = screen.getByRole("button", { name: "Start Mission" }) as HTMLButtonElement;
    expect(startButton.disabled).toBe(true);
    expect(screen.getByText("Finish or go back from probability-map setup before starting.")).toBeTruthy();
  });
});
