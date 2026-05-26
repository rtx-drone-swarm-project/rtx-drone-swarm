import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import BenchmarkPanel from "./BenchmarkPanel";

const clientMocks = vi.hoisted(() => ({
  startBenchmark: vi.fn(),
  stopBenchmark: vi.fn(),
  getBenchmarkRun: vi.fn(),
  listBenchmarkRuns: vi.fn(),
  listBenchmarkScenarios: vi.fn()
}));

vi.mock("../../api/missionClient", () => ({
  createMissionClient: vi.fn(() => clientMocks)
}));

const bounds = {
  min_lat: 33.45,
  max_lat: 33.55,
  min_lon: -117.25,
  max_lon: -117.15
};

const algorithmOptions = [
  { key: "voronoi", label: "Voronoi (Lloyd's)" },
  { key: "vaco", label: "VACO Hybrid Coverage (Kaydee)" }
];

const scenarioProfiles = [
  {
    key: "uniform_random",
    label: "Uniform Random",
    description: "Stationary baseline.",
    targets_move: false
  },
  {
    key: "wandering_hikers",
    label: "Wandering Hikers",
    description: "Moving hikers with deterministic drift.",
    targets_move: true
  }
];

function renderOpenPanel(props: Partial<ComponentProps<typeof BenchmarkPanel>> = {}) {
  const result = render(
    <BenchmarkPanel
      apiBase="http://localhost:8000"
      selectedBounds={bounds}
      validDroneCount={2}
      progressMessage={null}
      algorithmOptions={algorithmOptions}
      {...props}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: /Metrics/ }));
  return result;
}

describe("BenchmarkPanel", () => {
  beforeEach(() => {
    clientMocks.startBenchmark.mockReset();
    clientMocks.stopBenchmark.mockReset();
    clientMocks.getBenchmarkRun.mockReset();
    clientMocks.listBenchmarkRuns.mockReset();
    clientMocks.listBenchmarkScenarios.mockReset();
    clientMocks.listBenchmarkRuns.mockResolvedValue({ runs: [] });
    clientMocks.listBenchmarkScenarios.mockResolvedValue({ scenarios: scenarioProfiles });
    clientMocks.startBenchmark.mockResolvedValue({
      run_id: "bench-1",
      status: "running",
      total_trials: 4,
      completed_trials: 0,
      summary: {}
    });
    clientMocks.stopBenchmark.mockResolvedValue({ run_id: "bench-1", stopping: true });
    clientMocks.getBenchmarkRun.mockResolvedValue({
      run_id: "bench-1",
      status: "cancelled",
      total_trials: 4,
      completed_trials: 1,
      summary: {}
    });
  });

  it("enables start only when a search area and algorithms are selected, then enables stop for a running run", async () => {
    const { rerender } = renderOpenPanel({ selectedBounds: null });

    expect((screen.getByRole("button", { name: "Run Metrics" }) as HTMLButtonElement).disabled).toBe(true);

    rerender(
      <BenchmarkPanel
        apiBase="http://localhost:8000"
        selectedBounds={bounds}
        validDroneCount={2}
        progressMessage={null}
        algorithmOptions={algorithmOptions}
      />
    );

    await waitFor(() => {
      expect((screen.getByRole("button", { name: "Run Metrics" }) as HTMLButtonElement).disabled).toBe(false);
    });

    const scenario = await screen.findByLabelText("Scenario");
    fireEvent.change(scenario, { target: { value: "wandering_hikers" } });

    fireEvent.click(screen.getByRole("button", { name: "Run Metrics" }));

    await waitFor(() => {
      expect(clientMocks.startBenchmark).toHaveBeenCalledWith(
        expect.objectContaining({
          algorithms: ["voronoi", "vaco"],
          bounds,
          drone_count: 2,
          scenario_profile: "wandering_hikers"
        })
      );
    });

    await waitFor(() => {
      expect((screen.getByRole("button", { name: "Stop Metrics" }) as HTMLButtonElement).disabled).toBe(false);
    });

    fireEvent.click(screen.getByRole("button", { name: "Stop Metrics" }));

    await waitFor(() => {
      expect(clientMocks.stopBenchmark).toHaveBeenCalledWith("bench-1");
    });
  });

  it("calculates progress from the matching websocket progress message", async () => {
    const { container } = renderOpenPanel({
      progressMessage: { type: "benchmark_progress", run_id: "bench-1", completed: 2, total: 4, status: "running" }
    });

    await waitFor(() => {
      expect((screen.getByRole("button", { name: "Run Metrics" }) as HTMLButtonElement).disabled).toBe(false);
    });

    fireEvent.click(screen.getByRole("button", { name: "Run Metrics" }));

    await waitFor(() => {
      expect(screen.getByText("2/4")).toBeTruthy();
    });

    const fill = container.querySelector(".benchmark-progress .progress-fill") as HTMLElement | null;
    expect(fill?.style.width).toBe("50%");
  });

  it("loads a selected run from run history", async () => {
    clientMocks.listBenchmarkRuns.mockResolvedValue({
      runs: [
        {
          run_id: "bench-old",
          status: "complete",
          total_trials: 2,
          completed_trials: 2,
          request: { scenario_profile: "uniform_random" },
          summary: {}
        },
        {
          run_id: "bench-new",
          status: "complete",
          total_trials: 2,
          completed_trials: 2,
          request: { scenario_profile: "wandering_hikers" },
          summary: {}
        }
      ]
    });
    clientMocks.getBenchmarkRun.mockResolvedValue({
      run_id: "bench-new",
      status: "complete",
      total_trials: 2,
      completed_trials: 2,
      request: { scenario_profile: "wandering_hikers" },
      summary: {
        vaco: {
          count: 1,
          first_find_seconds: { mean: 82, min: 82, max: 82, stddev: 0 },
          coverage_pct: { mean: 88.2, min: 88.2, max: 88.2, stddev: 0 }
        }
      }
    });

    renderOpenPanel();

    const history = await screen.findByLabelText("Metrics History");
    fireEvent.change(history, { target: { value: "bench-new" } });

    await waitFor(() => {
      expect(clientMocks.getBenchmarkRun).toHaveBeenCalledWith("bench-new");
    });
    expect(await screen.findByText("vaco")).toBeTruthy();
    expect(screen.getByText("00:01:22 +/- 00:00:00")).toBeTruthy();
    expect(screen.getByText("88.2 +/- 0.0%")).toBeTruthy();
  });

  it("shows raw CSV and Markdown report export links for a loaded run", async () => {
    clientMocks.listBenchmarkRuns.mockResolvedValue({
      runs: [
        {
          run_id: "bench-report",
          status: "complete",
          total_trials: 2,
          completed_trials: 2,
          request: { scenario_profile: "uniform_random" },
          summary: {}
        }
      ]
    });
    clientMocks.getBenchmarkRun.mockResolvedValue({
      run_id: "bench-report",
      status: "complete",
      total_trials: 2,
      completed_trials: 2,
      request: { scenario_profile: "uniform_random" },
      summary: {}
    });

    renderOpenPanel();

    const history = await screen.findByLabelText("Metrics History");
    fireEvent.change(history, { target: { value: "bench-report" } });

    const csvLink = await screen.findByRole("link", { name: "Export Metrics CSV" });
    const reportLink = screen.getByRole("link", { name: "Export Report Markdown" });
    expect(csvLink.getAttribute("href")).toBe("http://localhost:8000/benchmark/export?run_id=bench-report");
    expect(reportLink.getAttribute("href")).toBe("http://localhost:8000/benchmark/bench-report/report.md");
  });
});
