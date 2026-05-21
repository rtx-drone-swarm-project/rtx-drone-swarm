import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import NavigationPanel from "./NavigationPanel";

function renderPanel(overrides: Partial<React.ComponentProps<typeof NavigationPanel>> = {}) {
  const defaults = {
    setupStage: "search_area" as const,
    topLeftLat: "33.550000",
    topLeftLon: "-117.250000",
    bottomRightLat: "33.450000",
    bottomRightLon: "-117.150000",
    selectedBounds: null,
    gridShape: undefined,
    isValidBounds: true,
    missionActive: false,
    missionLocked: false,
    missionStatus: "idle",
    searchAreaConfirmed: true,
    temporaryRegionSelectedCellCount: 0,
    temporaryRegionLabel: "" as const,
    showLabelledRegions: true,
    showProbabilityHeatmap: false,
    hasCustomProbabilityLabels: false,
    probabilityMapAvailable: false,
    searchAreaEditingDisabled: false,
    onTopLeftLatChange: vi.fn(),
    onTopLeftLonChange: vi.fn(),
    onBottomRightLatChange: vi.fn(),
    onBottomRightLonChange: vi.fn(),
    onSetSearchArea: vi.fn(),
    onConfigureProbabilityMap: vi.fn(),
    onShowLabelledRegionsChange: vi.fn(),
    onShowProbabilityHeatmapChange: vi.fn(),
    onTemporaryRegionLabelChange: vi.fn(),
    onApplyTemporaryRegion: vi.fn(),
    onCancelTemporaryRegion: vi.fn(),
    onBackFromLabelRegions: vi.fn(),
    onConfirmLabelledRegions: vi.fn(),
    onBackFromReview: vi.fn(),
  };
  return render(<NavigationPanel {...defaults} {...overrides} />);
}

describe("NavigationPanel", () => {
  it("renders four corner inputs plus search-area actions", () => {
    renderPanel();

    expect(screen.getByText("Search Area")).toBeTruthy();
    expect(screen.getByLabelText("Top-left latitude")).toBeTruthy();
    expect(screen.getByLabelText("Top-left longitude")).toBeTruthy();
    expect(screen.getByLabelText("Bottom-right latitude")).toBeTruthy();
    expect(screen.getByLabelText("Bottom-right longitude")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Set Search Area" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Configure Probability Map" })).toBeTruthy();
  });

  it("does not render the Pan to Drones button", () => {
    renderPanel();
    expect(screen.queryByRole("button", { name: /pan to drones/i })).toBeNull();
  });

  it("does not render hint text paragraphs", () => {
    renderPanel();
    expect(screen.queryByText(/Creates a/i)).toBeNull();
    expect(screen.queryByText(/Google Maps/i)).toBeNull();
    expect(screen.queryByText(/No drone positions/i)).toBeNull();
  });

  it("calls onSetSearchArea when button is clicked", () => {
    const onSetSearchArea = vi.fn();
    renderPanel({ onSetSearchArea });

    fireEvent.click(screen.getByRole("button", { name: "Set Search Area" }));
    expect(onSetSearchArea).toHaveBeenCalledTimes(1);
  });

  it("calls onConfigureProbabilityMap when confirm button is clicked", () => {
    const onConfigureProbabilityMap = vi.fn();
    renderPanel({ onConfigureProbabilityMap });

    fireEvent.click(screen.getByRole("button", { name: "Configure Probability Map" }));
    expect(onConfigureProbabilityMap).toHaveBeenCalledTimes(1);
  });

  it("disables Set Search Area when missionActive is true", () => {
    renderPanel({ missionActive: true });
    const btn = screen.getByRole("button", { name: "Set Search Area" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    const confirmBtn = screen.getByRole("button", { name: "Configure Probability Map" }) as HTMLButtonElement;
    expect(confirmBtn.disabled).toBe(true);
  });

  it("disables Set Search Area when bounds are invalid", () => {
    renderPanel({ isValidBounds: false });
    const btn = screen.getByRole("button", { name: "Set Search Area" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(screen.getByText(/rectangle must have non-zero width and height/i)).toBeTruthy();
  });

  it("calls onTopLeftLatChange when the top-left latitude input changes", () => {
    const onTopLeftLatChange = vi.fn();
    renderPanel({ onTopLeftLatChange });

    fireEvent.change(screen.getByLabelText("Top-left latitude"), { target: { value: "34.0" } });
    expect(onTopLeftLatChange).toHaveBeenCalledWith("34.0");
  });

  it("calls onBottomRightLonChange when the bottom-right longitude input changes", () => {
    const onBottomRightLonChange = vi.fn();
    renderPanel({ onBottomRightLonChange });

    fireEvent.change(screen.getByLabelText("Bottom-right longitude"), { target: { value: "-118.0" } });
    expect(onBottomRightLonChange).toHaveBeenCalledWith("-118.0");
  });

  it("renders label-regions stage with instruction, legend, and confirm button", () => {
    renderPanel({ setupStage: "label_regions" });

    expect(screen.getByText("Hold Shift and drag on the map to select a region.")).toBeTruthy();
    expect(screen.getByText("Region label legend")).toBeTruthy();
    expect(screen.getByText("Very unlikely")).toBeTruthy();
    expect(screen.getByText("Excluded")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Confirm Labelled Regions" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Set Search Area" })).toBeNull();
    expect(screen.getByRole("button", { name: "Back" })).toBeTruthy();
  });

  it("shows temporary region controls once cells are selected", () => {
    const onApplyTemporaryRegion = vi.fn();
    const onCancelTemporaryRegion = vi.fn();
    renderPanel({
      setupStage: "label_regions",
      temporaryRegionSelectedCellCount: 6,
      temporaryRegionLabel: "likely",
      onApplyTemporaryRegion,
      onCancelTemporaryRegion
    });

    expect(screen.getByText("Selected cells")).toBeTruthy();
    expect(screen.getByText("6")).toBeTruthy();
    expect(screen.getByLabelText("Region label")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Confirm Labelled Regions" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Apply Region" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel Selection" }));

    expect(onApplyTemporaryRegion).toHaveBeenCalledTimes(1);
    expect(onCancelTemporaryRegion).toHaveBeenCalledTimes(1);
  });

  it("renders the post-confirmation probability review panel", () => {
    const onBackFromReview = vi.fn();
    const onShowProbabilityHeatmapChange = vi.fn();

    renderPanel({
      setupStage: "review_probability_map",
      selectedBounds: {
        min_lat: 33.45,
        max_lat: 33.55,
        min_lon: -117.25,
        max_lon: -117.15,
      },
      gridShape: [4, 6],
      showProbabilityHeatmap: true,
      showLabelledRegions: false,
      onBackFromReview,
      onShowProbabilityHeatmapChange,
    });

    expect(screen.getByText("Mission Map")).toBeTruthy();
    expect(screen.getByText("Search area bounds")).toBeTruthy();
    expect(screen.getByText("Grid shape")).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "Show probability heatmap" })).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "Show labelled regions" })).toBeTruthy();
    expect(screen.getByText("Heatmap legend")).toBeTruthy();
    expect(screen.getByText("Low probability")).toBeTruthy();
    expect(screen.getByText("High probability")).toBeTruthy();
    expect(screen.queryByText("Region label legend")).toBeNull();
    expect(screen.getByRole("button", { name: "Back" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Confirm Labelled Regions" })).toBeNull();

    fireEvent.click(screen.getByRole("checkbox", { name: "Show probability heatmap" }));
    expect(onShowProbabilityHeatmapChange).toHaveBeenCalledWith(false);

    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(onBackFromReview).toHaveBeenCalledTimes(1);
  });

  it("shows the raw label legend separately in review mode when labelled regions are enabled", () => {
    renderPanel({
      setupStage: "review_probability_map",
      showProbabilityHeatmap: false,
      showLabelledRegions: true,
      probabilityMapAvailable: true,
    });

    expect(screen.queryByText("Heatmap legend")).toBeNull();
    expect(screen.getByText("Region label legend")).toBeTruthy();
  });

  it("shows probability toggles during an active mission when a probability map exists", () => {
    renderPanel({
      setupStage: "active_mission",
      probabilityMapAvailable: true,
      selectedBounds: {
        min_lat: 33.45,
        max_lat: 33.55,
        min_lon: -117.25,
        max_lon: -117.15,
      },
      gridShape: [4, 6],
      showProbabilityHeatmap: false,
      showLabelledRegions: false,
    });

    expect(screen.getByText("Mission Map")).toBeTruthy();
    expect(screen.getByText("Search area bounds")).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "Show probability heatmap" })).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "Show labelled regions" })).toBeTruthy();
    expect(screen.getByText("Probability overlays are hidden during active missions by default. Use toggles to show them.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Back" })).toBeNull();
  });
});
