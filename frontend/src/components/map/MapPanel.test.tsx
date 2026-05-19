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
const mocks = vi.hoisted(() => ({
  marker: vi.fn((_props: Record<string, unknown>) => null),
  polyline: vi.fn((_props: Record<string, unknown>) => null),
  rectangle: vi.fn((_props: Record<string, unknown>) => null),
  makeCentroidIcon: vi.fn((_label: string, _phase?: string | null) => ({ icon: "centroid" })),
  makeDroneIcon: vi.fn((_label: string, _role?: string | null, _heading?: number) => ({ icon: "drone" })),
  makePlacedHikerIcon: vi.fn((_label: string, _movement: string, _locked?: boolean) => ({ icon: "placed-hiker" })),
  makeTargetCircleIcon: vi.fn((_label: string, _status?: string | null) => ({ icon: "target" }))
}));
let mapEventHandlers: Record<string, () => void> = {};

vi.mock("react-leaflet", () => ({
  MapContainer: ({ children }: { children: React.ReactNode }) => <div data-testid="map-container">{children}</div>,
  TileLayer: () => null,
  Marker: mocks.marker,
  Polyline: mocks.polyline,
  Rectangle: mocks.rectangle,
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

vi.mock("./MapClickSelector", () => ({ default: () => null }));
vi.mock("./MapRecenter", () => ({ default: () => null }));
vi.mock("./icons", () => ({
  makeCentroidIcon: mocks.makeCentroidIcon,
  makeDroneIcon: mocks.makeDroneIcon,
  makePlacedHikerIcon: mocks.makePlacedHikerIcon,
  makeTargetCircleIcon: mocks.makeTargetCircleIcon
}));

const bboxDrawerMock = vi.hoisted(() => ({
  props: [] as any[]
}));

vi.mock("./MapBBoxDrawer", () => ({
  default: (props: Record<string, unknown>) => {
    bboxDrawerMock.props.push(props);
    return null;
  }
}));

const defaultProps = {
  defaultCenter: [33.5, -117.2] as [number, number],
  defaultZoom: 13,
  mapCenter: null,
  selectedBounds: null,
  gridShape: undefined,
  probabilityMapMode: false,
  missionActive: false,
  validDrones: [],
  targets: [],
  placedHikers: [],
  hikerPlacementEditable: false,
  hikerPlacementMode: false,
  getHikerLabel: (id: string | number) => `Hiker ${id}`,
  getPlacedHikerLabel: (_hiker: any, index: number) => `Hiker ${index + 1}`,
  setSelectedDrone: vi.fn(),
  onSelectHiker: vi.fn(),
  onPlaceHiker: vi.fn(),
  onMoveHiker: vi.fn(),
  onSelectArea: vi.fn(),
  onSelectTemporaryRegion: vi.fn(),
  temporaryRegionBounds: null,
  temporaryRegionCells: []
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
    mocks.marker.mockClear();
    mocks.polyline.mockClear();
    mocks.rectangle.mockClear();
    mocks.makeCentroidIcon.mockClear();
    mocks.makeDroneIcon.mockClear();
    mocks.makePlacedHikerIcon.mockClear();
    mocks.makeTargetCircleIcon.mockClear();
    bboxDrawerMock.props = [];
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

  it("labels sweep centroids clearly and updates marker position when telemetry changes", () => {
    const { rerender } = render(
      <MapPanel
        {...defaultProps}
        missionActive
        selectedAlgorithm="sweep"
        validDrones={[
          {
            id: "1",
            lat: 33.5,
            lon: -117.2,
            sweep_centroid: [33.51, -117.21],
            sweep_phase: "en_route"
          }
        ]}
      />
    );

    expect(mocks.makeCentroidIcon).toHaveBeenLastCalledWith("D1 centroid", "en_route");
    let centroidMarkers = mocks.marker.mock.calls.map(([props]) => props).filter((props) => props.interactive === false);
    expect(centroidMarkers[centroidMarkers.length - 1]?.position).toEqual([33.51, -117.21]);

    mocks.marker.mockClear();
    mocks.makeCentroidIcon.mockClear();
    rerender(
      <MapPanel
        {...defaultProps}
        missionActive
        selectedAlgorithm="sweep"
        validDrones={[
          {
            id: "1",
            lat: 33.52,
            lon: -117.22,
            sweep_centroid: [33.53, -117.23],
            sweep_phase: "sweeping"
          }
        ]}
      />
    );

    expect(mocks.makeCentroidIcon).toHaveBeenLastCalledWith("D1 centroid", "sweeping");
    centroidMarkers = mocks.marker.mock.calls.map(([props]) => props).filter((props) => props.interactive === false);
    expect(centroidMarkers[centroidMarkers.length - 1]?.position).toEqual([33.53, -117.23]);
  });

  it("hides stale centroid markers when the selected algorithm is not sweep", () => {
    render(
      <MapPanel
        {...defaultProps}
        missionActive
        selectedAlgorithm="apf"
        validDrones={[
          {
            id: "1",
            lat: 33.5,
            lon: -117.2,
            sweep_centroid: [33.51, -117.21],
            sweep_phase: "sweeping"
          }
        ]}
      />
    );

    expect(mocks.makeCentroidIcon).not.toHaveBeenCalled();
  });

  it("renders sweep trails with stronger styling", () => {
    render(
      <MapPanel
        {...defaultProps}
        missionActive
        selectedAlgorithm="sweep"
        validDrones={[{ id: "1", lat: 33.5, lon: -117.2 }]}
        droneTrails={{ "1": [[33.5, -117.2], [33.51, -117.21]] }}
      />
    );

    const trailProps = mocks.polyline.mock.calls[0][0];
    expect(trailProps.positions).toEqual([[33.5, -117.2], [33.51, -117.21]]);
    expect(trailProps.pathOptions).toEqual(
      expect.objectContaining({
        weight: 4,
        opacity: 0.92,
        className: "sweep-drone-trail"
      })
    );
  });

  it("renders placed hikers as draggable markers before mission start", () => {
    const onMoveHiker = vi.fn();
    const onSelectHiker = vi.fn();
    render(
      <MapPanel
        {...defaultProps}
        hikerPlacementEditable
        placedHikers={[{ id: "hiker-1", lat: 33.51, lon: -117.21, movement: "stationary" }]}
        onMoveHiker={onMoveHiker}
        onSelectHiker={onSelectHiker}
      />
    );

    expect(mocks.makePlacedHikerIcon).toHaveBeenCalledWith("Hiker 1", "stationary", false);
    const markerProps = mocks.marker.mock.calls.map(([props]) => props).find((props) => props.draggable === true);
    expect(markerProps?.position).toEqual([33.51, -117.21]);
  });

  it("passes drawn bounds straight through to the area-selection callback", () => {
    const onSelectArea = vi.fn();
    render(<MapPanel {...defaultProps} onSelectArea={onSelectArea} />);

    const searchAreaDrawerProps = bboxDrawerMock.props[0];
    searchAreaDrawerProps.onBoundsDrawn({
      min_lat: 33.45,
      max_lat: 33.55,
      min_lon: -117.25,
      max_lon: -117.15
    });

    expect(onSelectArea).toHaveBeenCalledWith({
      min_lat: 33.45,
      max_lat: 33.55,
      min_lon: -117.25,
      max_lon: -117.15
    });
  });

  it("switches shift-drag handling to temporary region selection in probability-map mode", () => {
    const onSelectTemporaryRegion = vi.fn();
    render(
      <MapPanel
        {...defaultProps}
        probabilityMapMode
        onSelectTemporaryRegion={onSelectTemporaryRegion}
      />
    );

    expect(bboxDrawerMock.props).toHaveLength(2);
    expect(bboxDrawerMock.props[0].enabled).toBe(false);
    expect(bboxDrawerMock.props[1].enabled).toBe(true);

    bboxDrawerMock.props[1].onBoundsDrawn({
      min_lat: 33.46,
      max_lat: 33.5,
      min_lon: -117.24,
      max_lon: -117.2
    });

    expect(onSelectTemporaryRegion).toHaveBeenCalledWith({
      min_lat: 33.46,
      max_lat: 33.5,
      min_lon: -117.24,
      max_lon: -117.2
    });
  });

  it("renders temporary region cells as highlighted rectangles", () => {
    render(
      <MapPanel
        {...defaultProps}
        selectedBounds={{ min_lat: 33.45, max_lat: 33.55, min_lon: -117.25, max_lon: -117.15 }}
        gridShape={[2, 2]}
        temporaryRegionBounds={{ min_lat: 33.45, max_lat: 33.5, min_lon: -117.25, max_lon: -117.2 }}
        temporaryRegionCells={[[0, 1], [1, 0]]}
      />
    );

    const temporaryCellCalls = mocks.rectangle.mock.calls
      .map(([props]) => props)
      .filter((props) => (props.pathOptions as { fillColor?: string } | undefined)?.fillColor === "#f97316");

    expect(temporaryCellCalls).toHaveLength(2);
    expect(temporaryCellCalls[0]?.bounds).toEqual([[33.5, -117.2], [33.55, -117.15]]);
    expect(temporaryCellCalls[1]?.bounds).toEqual([[33.45, -117.25], [33.5, -117.2]]);
  });

  it("hides placed hiker markers that already exist as runtime targets", () => {
    render(
      <MapPanel
        {...defaultProps}
        missionActive
        targets={[{ id: "hiker-1", lat: 33.51, lon: -117.21, status: "wandering" }]}
        placedHikers={[
          { id: "hiker-1", lat: 33.51, lon: -117.21, movement: "stationary" },
          { id: "hiker-2", lat: 33.52, lon: -117.22, movement: "moving" }
        ]}
      />
    );

    expect(mocks.makeTargetCircleIcon).toHaveBeenCalledWith("Hiker hiker-1", "wandering");
    expect(mocks.makePlacedHikerIcon).toHaveBeenCalledTimes(1);
    expect(mocks.makePlacedHikerIcon).toHaveBeenCalledWith("Hiker 2", "moving", true);
  });
});
