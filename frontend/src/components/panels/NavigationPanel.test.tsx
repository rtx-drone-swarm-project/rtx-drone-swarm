import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import NavigationPanel from "./NavigationPanel";

function renderPanel(overrides: Partial<React.ComponentProps<typeof NavigationPanel>> = {}) {
  const defaults = {
    topLeftLat: "33.550000",
    topLeftLon: "-117.250000",
    bottomRightLat: "33.450000",
    bottomRightLon: "-117.150000",
    isValidBounds: true,
    missionActive: false,
    onTopLeftLatChange: vi.fn(),
    onTopLeftLonChange: vi.fn(),
    onBottomRightLatChange: vi.fn(),
    onBottomRightLonChange: vi.fn(),
    onSetSearchArea: vi.fn()
  };
  return render(<NavigationPanel {...defaults} {...overrides} />);
}

describe("NavigationPanel", () => {
  it("renders four corner inputs and Set Search Area button", () => {
    renderPanel();

    expect(screen.getByText("Navigation")).toBeTruthy();
    expect(screen.getByLabelText("Top-left latitude")).toBeTruthy();
    expect(screen.getByLabelText("Top-left longitude")).toBeTruthy();
    expect(screen.getByLabelText("Bottom-right latitude")).toBeTruthy();
    expect(screen.getByLabelText("Bottom-right longitude")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Set Search Area" })).toBeTruthy();
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

  it("disables Set Search Area when missionActive is true", () => {
    renderPanel({ missionActive: true });
    const btn = screen.getByRole("button", { name: "Set Search Area" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
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
});
