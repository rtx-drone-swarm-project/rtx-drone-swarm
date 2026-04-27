import { act, render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MapPanel from "./MapPanel";

const flyTo = vi.fn();
const getCenter = vi.fn(() => ({ lat: 33.5, lng: -117.2 }));
const getZoom = vi.fn(() => 13);
const stop = vi.fn();
const setZoom = vi.fn();
const once = vi.fn((eventName: string, handler: () => void) => {
  mapEventHandlers[eventName] = handler;
});
const off = vi.fn();
let mapEventHandlers: Record<string, () => void> = {};

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children: React.ReactNode }) => <div data-testid="map-container">{children}</div>,
  TileLayer: () => null,
  Marker: () => null,
  Rectangle: () => null,
  useMap: () => ({
    flyTo,
    getCenter,
    getZoom,
    getMinZoom: vi.fn(() => 1),
    getMaxZoom: vi.fn(() => 18),
    stop,
    setZoom,
    once,
    off
  })
}));

vi.mock("./MapBBoxDrawer", () => ({ default: () => null }));
vi.mock("./MapRecenter", () => ({ default: () => null }));
vi.mock("./icons", () => ({
  makeDroneIcon: vi.fn(() => ({})),
  makeTargetCircleIcon: vi.fn(() => ({}))
}));

const defaultProps = {
  defaultCenter: [33.5, -117.2] as [number, number],
  defaultZoom: 13,
  mapCenter: null,
  selectedBounds: null,
  missionActive: false,
  validDrones: [],
  targets: [],
  getHikerLabel: (id: string | number) => `Hiker ${id}`,
  setSelectedDrone: vi.fn(),
  onSelectArea: vi.fn()
};

describe("MapPanel", () => {
  beforeEach(() => {
    flyTo.mockClear();
    getCenter.mockClear();
    getZoom.mockClear();
    stop.mockClear();
    setZoom.mockClear();
    once.mockClear();
    off.mockClear();
    mapEventHandlers = {};
  });

  it("renders the custom map controls", () => {
    render(<MapPanel {...defaultProps} />);
    expect(screen.getByRole("button", { name: "Pan to drones" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Zoom in" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Zoom out" })).toBeTruthy();
  });

  it("renders the map container", () => {
    render(<MapPanel {...defaultProps} />);
    expect(screen.getByTestId("map-container")).toBeTruthy();
  });

  it("pan button is disabled when hasDrones is false", () => {
    render(<MapPanel {...defaultProps} validDrones={[]} />);
    const btn = screen.getByRole("button", { name: "Pan to drones" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("pan button is enabled when hasDrones is true", () => {
    render(<MapPanel {...defaultProps} validDrones={[{ id: "1", lat: 33.51, lon: -117.21 }]} />);
    const btn = screen.getByRole("button", { name: "Pan to drones" }) as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });

  it("does not fly to drones when clicked with no drones", () => {
    render(<MapPanel {...defaultProps} validDrones={[]} />);
    fireEvent.click(screen.getByRole("button", { name: "Pan to drones" }));
    expect(flyTo).not.toHaveBeenCalled();
  });

  it("flies to the average drone location and zooms in slightly", () => {
    render(
      <MapPanel
        {...defaultProps}
        validDrones={[
          { id: "1", lat: 33.5, lon: -117.2 },
          { id: "2", lat: 33.52, lon: -117.22 }
        ]}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Pan to drones" }));
    expect(stop).toHaveBeenCalledTimes(1);
    expect(once).toHaveBeenCalledWith("moveend", expect.any(Function));
    expect(flyTo).toHaveBeenCalledWith([33.510000000000005, -117.21000000000001], 14, {
      animate: true,
      duration: 0.7
    });
  });

  it("uses zoom-only map updates for zoom controls", () => {
    render(<MapPanel {...defaultProps} />);

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(once).toHaveBeenCalledWith("zoomend", expect.any(Function));
    act(() => {
      mapEventHandlers.zoomend();
    });
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));

    expect(stop).toHaveBeenCalledTimes(2);
    expect(flyTo).not.toHaveBeenCalled();
    expect(setZoom).toHaveBeenNthCalledWith(1, 14, { animate: true });
    expect(setZoom).toHaveBeenNthCalledWith(2, 12, { animate: true });
  });

  it("ignores repeated zoom clicks while the map is settling", () => {
    render(<MapPanel {...defaultProps} />);

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));

    expect(stop).toHaveBeenCalledTimes(1);
    expect(setZoom).toHaveBeenCalledTimes(1);
  });
});
