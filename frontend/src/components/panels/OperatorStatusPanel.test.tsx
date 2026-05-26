import { render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it } from "vitest";
import OperatorStatusPanel from "./OperatorStatusPanel";

const bounds = {
  min_lat: 33.45,
  max_lat: 33.55,
  min_lon: -117.25,
  max_lon: -117.15
};

function renderPanel(
  props: Partial<ComponentProps<typeof OperatorStatusPanel>> = {}
) {
  return render(
    <OperatorStatusPanel
      elapsedSeconds={0}
      droneCount={15}
      missionComplete={false}
      missionStatus="idle"
      placedHikerCount={0}
      progress={0}
      selectedBounds={null}
      targets={[]}
      telemetryMode="LIVE SITL"
      {...props}
    />
  );
}

describe("OperatorStatusPanel", () => {
  it("shows the select-area cue when idle without a search area", () => {
    renderPanel();

    expect(screen.getByText("Operator Status")).toBeTruthy();
    expect(screen.getByText("Select a search area to begin.")).toBeTruthy();
    expect(screen.getByText("Not selected")).toBeTruthy();
    expect(screen.getByText("Random hikers on start")).toBeTruthy();
  });

  it("shows ready-to-start cue and estimated area when bounds are selected", () => {
    renderPanel({ selectedBounds: bounds });

    expect(screen.getByText("Area selected. Start mission when ready.")).toBeTruthy();
    expect(screen.getByText("103 km2")).toBeTruthy();
  });

  it("shows searching SAR details with a single drone count", () => {
    const { container } = renderPanel({
      elapsedSeconds: 125,
      droneCount: 12,
      missionStatus: "searching",
      placedHikerCount: 3,
      progress: 42,
      selectedBounds: bounds,
      targets: [
        { id: "h1", lat: 33.51, lon: -117.21, status: "found" },
        { id: "h2", lat: 33.52, lon: -117.22, status: "wandering" },
        { id: "h3", lat: 33.53, lon: -117.23, status: "wandering" }
      ]
    });

    expect(container.textContent).toContain("Search in progress. Monitor found hiker updates.");
    expect(screen.getByText("00:02:05")).toBeTruthy();
    expect(screen.getByText("42%")).toBeTruthy();
    expect(screen.getByText("1/3 found, 2 remaining")).toBeTruthy();
    expect(screen.getByText("Drones Assigned")).toBeTruthy();
    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.queryByText("Algorithm")).toBeNull();
    expect(screen.queryByText("PMV (Probability Map Voronoi)")).toBeNull();
    expect(screen.queryByText("Active Drones")).toBeNull();
    expect(screen.queryByText("Valid Drones")).toBeNull();
    expect(screen.queryByText("WebSocket")).toBeNull();
    expect(screen.queryByText("Connected")).toBeNull();
    expect(screen.queryByText("Disconnected")).toBeNull();
  });

  it("shows recall and completion cues for terminal search states", () => {
    const { rerender } = renderPanel({
      missionStatus: "search_complete",
      selectedBounds: bounds,
      progress: 100,
      targets: [{ id: "h1", lat: 33.51, lon: -117.21, status: "found" }]
    });

    expect(screen.getByText("All hikers found. Recall drones.")).toBeTruthy();

    rerender(
      <OperatorStatusPanel
        elapsedSeconds={200}
        droneCount={15}
        missionComplete
        missionStatus="mission_complete"
        placedHikerCount={0}
        progress={100}
        selectedBounds={bounds}
        targets={[{ id: "h1", lat: 33.51, lon: -117.21, status: "found" }]}
        telemetryMode="LIVE SITL"
      />
    );

    expect(screen.getByText("Mission complete. Reset mission when ready for the next search.")).toBeTruthy();
  });

  it("renders long active-state cues through the wrapping label", () => {
    const { container, rerender } = renderPanel({
      missionStatus: "searching",
      selectedBounds: bounds,
      targets: [{ id: "h1", lat: 33.51, lon: -117.21, status: "wandering" }]
    });

    expect(container.querySelector(".searching-label")?.textContent).toContain("Search in progress. Monitor found hiker updates.");

    rerender(
      <OperatorStatusPanel
        elapsedSeconds={40}
        droneCount={15}
        missionComplete={false}
        missionStatus="recalling"
        placedHikerCount={0}
        progress={100}
        selectedBounds={bounds}
        targets={[{ id: "h1", lat: 33.51, lon: -117.21, status: "found" }]}
        telemetryMode="LIVE SITL"
      />
    );

    expect(container.querySelector(".searching-label")?.textContent).toContain("Recall in progress. Monitor return status.");
  });
});
