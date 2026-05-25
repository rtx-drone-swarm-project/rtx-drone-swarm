import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import SearchSummaryModal from "./SearchSummaryModal";

const targets = [
  { id: "t1", lat: 33.51, lon: -117.21, status: "found" },
  { id: "t2", lat: 33.52, lon: -117.22, status: "found" }
];

function getHikerLabel(targetId: string | number) {
  return targetId === "t1" ? "Hiker 1" : "Hiker 2";
}

describe("SearchSummaryModal", () => {
  it("shows completion metrics without benchmark-only fields", () => {
    render(
      <SearchSummaryModal
        isOpen
        onClose={vi.fn()}
        targets={targets}
        getHikerLabel={getHikerLabel}
        onRecall={vi.fn()}
        completionElapsedSeconds={99}
        metrics={{
          algorithm: "pmv",
          status: "search_complete",
          elapsed_seconds: 100,
          completion_elapsed_seconds: 88,
          targets_total: 2,
          targets_found: 2,
          found_at_seconds: [12, 80],
          first_find_seconds: 12,
          last_find_seconds: 80,
          avg_find_seconds: 46,
          coverage_pct: 76.5,
          coverage_rate_per_sec: 0.76
        }}
      />
    );

    expect(screen.getByText("Hikers Found")).toBeTruthy();
    expect(screen.getByText("2/2")).toBeTruthy();
    expect(screen.getByText("Mission Duration")).toBeTruthy();
    expect(screen.getByText("88s")).toBeTruthy();
    expect(screen.getByText("Coverage")).toBeTruthy();
    expect(screen.getByText("76.5%")).toBeTruthy();
    expect(screen.getByText("First Find")).toBeTruthy();
    expect(screen.getByText("12s")).toBeTruthy();
    expect(screen.getByText("Last Find")).toBeTruthy();
    expect(screen.getByText("80s")).toBeTruthy();
    expect(screen.queryByText("Avg Find")).toBeNull();
    expect(screen.queryByText("Algorithm")).toBeNull();
  });

  it("falls back to target count and omits missing metrics", () => {
    render(
      <SearchSummaryModal
        isOpen
        onClose={vi.fn()}
        targets={targets}
        getHikerLabel={getHikerLabel}
        onRecall={vi.fn()}
      />
    );

    expect(screen.queryByText("Coverage")).toBeNull();
    expect(screen.queryByText("First Find")).toBeNull();
    expect(screen.queryByText("Last Find")).toBeNull();
    expect(screen.getByText("Final coordinates:")).toBeTruthy();
  });

  it("runs recall and closes when recall is requested", () => {
    const onClose = vi.fn();
    const onRecall = vi.fn();
    render(
      <SearchSummaryModal
        isOpen
        onClose={onClose}
        targets={targets}
        getHikerLabel={getHikerLabel}
        onRecall={onRecall}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Recall Drones" }));

    expect(onRecall).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
