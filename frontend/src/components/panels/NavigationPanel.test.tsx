import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import NavigationPanel from "./NavigationPanel";

function renderPanel(overrides: Partial<React.ComponentProps<typeof NavigationPanel>> = {}) {
  const defaults = {
    lat: "33.500000",
    lon: "-117.200000",
    isValidCoord: true,
    missionActive: false,
    onLatitudeChange: vi.fn(),
    onLongitudeChange: vi.fn(),
    onSetSearchArea: vi.fn()
  };
  return render(<NavigationPanel {...defaults} {...overrides} />);
}

describe("NavigationPanel", () => {
  it("renders lat, lon, size inputs and Set Search Area button", () => {
    renderPanel();

    expect(screen.getByText("Navigation")).toBeTruthy();
    expect(screen.getByPlaceholderText("e.g. 33.5000")).toBeTruthy();
    expect(screen.getByPlaceholderText("e.g. -117.2000")).toBeTruthy();
    expect(screen.getByText("Search Area Size (km)")).toBeTruthy();
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

  it("calls onSetSearchArea with the current sideKm when button is clicked", () => {
    const onSetSearchArea = vi.fn();
    renderPanel({ onSetSearchArea });

    fireEvent.click(screen.getByRole("button", { name: "Set Search Area" }));
    expect(onSetSearchArea).toHaveBeenCalledTimes(1);
    expect(onSetSearchArea).toHaveBeenCalledWith(4);
  });

  it("disables Set Search Area when missionActive is true", () => {
    renderPanel({ missionActive: true });
    const btn = screen.getByRole("button", { name: "Set Search Area" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("disables Set Search Area when coords are invalid", () => {
    renderPanel({ isValidCoord: false });
    const btn = screen.getByRole("button", { name: "Set Search Area" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    expect(screen.getByText(/Lat: -90..90/i)).toBeTruthy();
  });

  it("calls onLatitudeChange when lat input changes", () => {
    const onLatitudeChange = vi.fn();
    renderPanel({ onLatitudeChange });

    fireEvent.change(screen.getByPlaceholderText("e.g. 33.5000"), { target: { value: "34.0" } });
    expect(onLatitudeChange).toHaveBeenCalledWith("34.0");
  });

  it("calls onLongitudeChange when lon input changes", () => {
    const onLongitudeChange = vi.fn();
    renderPanel({ onLongitudeChange });

    fireEvent.change(screen.getByPlaceholderText("e.g. -117.2000"), { target: { value: "-118.0" } });
    expect(onLongitudeChange).toHaveBeenCalledWith("-118.0");
  });
});
