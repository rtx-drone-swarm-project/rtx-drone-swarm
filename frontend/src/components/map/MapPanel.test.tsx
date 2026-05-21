import { act, render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import MapPanel, { getGridCellBounds, getProbabilityHeatmapStats, isExcludedProbabilityCell } from "./MapPanel";

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
  mapContainer: vi.fn((_props: Record<string, unknown>) => null),
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
  MapContainer: (props: { children: React.ReactNode }) => {
    mocks.mapContainer(props);
    return <div data-testid="map-container">{props.children}</div>;
  },
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
  missionBounds: undefined,
  gridShape: undefined,
  setupStage: "search_area" as const,
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
  temporaryRegionCells: [],
  operatorLabelGrid: undefined,
  showLabelledRegions: true,
  probabilityGrid: undefined,
  showProbabilityHeatmap: false
};

type MockRectangleProps = {
  bounds: [[number, number], [number, number]];
  pathOptions?: { fillColor?: string; fillOpacity?: number };
};

function isPmvHeatmapRectangle(props: Record<string, unknown>) {
  const pathOptions = props.pathOptions as { className?: string } | undefined;
  return pathOptions?.className === "pmv-heatmap-cell";
}

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
    mocks.mapContainer.mockClear();
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

  it("renders probability overlays with mission bounds during an active mission", () => {
    render(
      <MapPanel
        {...defaultProps}
        setupStage="active_mission"
        missionActive
        selectedBounds={null}
        missionBounds={{
          min_lat: 33.45,
          max_lat: 33.55,
          min_lon: -117.25,
          max_lon: -117.15,
        }}
        gridShape={[2, 2]}
        operatorLabelGrid={[
          [2, 3],
          [2, 5],
        ]}
        searchableMask={[
          [true, true],
          [true, false],
        ]}
        probabilityGrid={[0.1, 0.2, 0.7, 0]}
        showLabelledRegions
        showProbabilityHeatmap
      />
    );

    const overlayCalls = mocks.rectangle.mock.calls.map(([props]) => props as MockRectangleProps);
    const heatmapCalls = overlayCalls.filter((props) => {
      const fillColor = props.pathOptions?.fillColor;
      return fillColor === "#bfdbfe" || fillColor === "#3b82f6" || fillColor === "#1e40af" || fillColor === "#1f2937";
    });
    expect(heatmapCalls.length).toBeGreaterThan(0);

    const labelledCalls = overlayCalls.filter((props) => {
      const fillColor = props.pathOptions?.fillColor;
      return fillColor === "#15803d" || fillColor === "#1f2937";
    });
    expect(labelledCalls.length).toBeGreaterThan(0);
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

  it("renders PMV heatmap rectangles only for active PMV missions", () => {
    render(
      <MapPanel
        {...defaultProps}
        missionActive
        selectedAlgorithm="pmv"
        pmvHeatmap={{
          type: "pmv_heatmap",
          mission_id: "mission-1",
          algorithm: "pmv",
          rows: 2,
          cols: 2,
          bounds: { min_lat: 0, max_lat: 2, min_lon: 10, max_lon: 12 },
          values: [0.1, 0.2, 0.3, 0.4],
          max_value: 0.4,
          total_probability: 1
        }}
      />
    );

    expect(screen.getByLabelText("PMV heatmap")).toBeTruthy();
    const heatmapRectangles = mocks.rectangle.mock.calls
      .map(([props]) => props)
      .filter(isPmvHeatmapRectangle);
    expect(heatmapRectangles).toHaveLength(4);
    expect(heatmapRectangles[0]?.bounds).toEqual([[0, 10], [1, 11]]);
    expect(heatmapRectangles[3]?.bounds).toEqual([[1, 11], [2, 12]]);
  });

  it("hides PMV heatmap rectangles for non-PMV algorithms and when toggled off", () => {
    const heatmap = {
      type: "pmv_heatmap" as const,
      mission_id: "mission-1",
      algorithm: "pmv",
      rows: 1,
      cols: 1,
      bounds: { min_lat: 0, max_lat: 1, min_lon: 0, max_lon: 1 },
      values: [1],
      max_value: 1,
      total_probability: 1
    };
    const { rerender } = render(
      <MapPanel
        {...defaultProps}
        missionActive
        selectedAlgorithm="sweep"
        pmvHeatmap={heatmap}
      />
    );

    expect(screen.queryByLabelText("PMV heatmap")).toBeNull();
    expect(mocks.rectangle.mock.calls.some(([props]) => isPmvHeatmapRectangle(props))).toBe(false);

    mocks.rectangle.mockClear();
    rerender(
      <MapPanel
        {...defaultProps}
        missionActive
        selectedAlgorithm="pmv"
        pmvHeatmap={heatmap}
      />
    );

    fireEvent.click(screen.getByLabelText("PMV heatmap"));

    mocks.rectangle.mockClear();
    rerender(
      <MapPanel
        {...defaultProps}
        missionActive
        selectedAlgorithm="pmv"
        pmvHeatmap={heatmap}
      />
    );

    expect(mocks.rectangle.mock.calls.some(([props]) => isPmvHeatmapRectangle(props))).toBe(false);
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
        setupStage="label_regions"
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
      .filter((props) => (props.pathOptions as { fillColor?: string } | undefined)?.fillColor === "#60a5fa");

    expect(temporaryCellCalls).toHaveLength(2);
    expect(temporaryCellCalls[0]?.bounds).toEqual([[33.45, -117.2], [33.5, -117.15]]);
    expect(temporaryCellCalls[1]?.bounds).toEqual([[33.5, -117.25], [33.55, -117.2]]);
  });

  it("renders applied labelled-region overlays for non-normal cells only", () => {
    render(
      <MapPanel
        {...defaultProps}
        setupStage="label_regions"
        selectedBounds={{ min_lat: 33.45, max_lat: 33.55, min_lon: -117.25, max_lon: -117.15 }}
        gridShape={[2, 3]}
        operatorLabelGrid={[
          [2, 3, 5],
          [0, 4, 1],
        ]}
      />
    );

    const appliedCellCalls = mocks.rectangle.mock.calls
      .map(([props]) => props)
      .filter((props) => {
        const fillColor = (props.pathOptions as { fillColor?: string } | undefined)?.fillColor;
        return fillColor != null && fillColor !== "#60a5fa";
      });

    expect(appliedCellCalls).toHaveLength(5);
    expect(appliedCellCalls.map((props) => props.bounds)).toEqual(
      expect.arrayContaining([
        [[33.45, -117.21666666666667], [33.5, -117.18333333333334]],
        [[33.45, -117.18333333333334], [33.5, -117.15]],
        [[33.5, -117.25], [33.55, -117.21666666666667]],
      ])
    );
  });

  it("hides applied labelled-region overlays when the toggle is off", () => {
    render(
      <MapPanel
        {...defaultProps}
        setupStage="label_regions"
        showLabelledRegions={false}
        selectedBounds={{ min_lat: 33.45, max_lat: 33.55, min_lon: -117.25, max_lon: -117.15 }}
        gridShape={[2, 2]}
        operatorLabelGrid={[
          [3, 5],
          [2, 4],
        ]}
      />
    );

    const appliedCellCalls = mocks.rectangle.mock.calls
      .map(([props]) => props)
      .filter((props) => {
        const fillColor = (props.pathOptions as { fillColor?: string } | undefined)?.fillColor;
        return fillColor != null && fillColor !== "#60a5fa";
      });

    expect(appliedCellCalls).toHaveLength(0);
  });

  it("renders excluded cells in gray and scales searchable positive cells from positive non-excluded values only", () => {
    render(
      <MapPanel
        {...defaultProps}
        setupStage="label_regions"
        selectedBounds={{ min_lat: 33.45, max_lat: 33.55, min_lon: -117.25, max_lon: -117.15 }}
        gridShape={[2, 2]}
        probabilityGrid={[0, 0.1, 0.3, 0.6]}
        operatorLabelGrid={[
          [5, 2],
          [2, 2],
        ]}
        searchableMask={[
          [false, true],
          [true, true],
        ]}
        showLabelledRegions={false}
        showProbabilityHeatmap
      />
    );

    const heatmapCalls = mocks.rectangle.mock.calls
      .map(([props]) => props as MockRectangleProps)
      .filter((props) => {
        const fillColor = (props.pathOptions as { fillColor?: string } | undefined)?.fillColor;
        return fillColor === "#bfdbfe" || fillColor === "#3b82f6" || fillColor === "#1e40af" || fillColor === "#1f2937";
      });

    expect(heatmapCalls).toHaveLength(4);
    expect(heatmapCalls.map((props) => props.bounds)).toEqual(
      expect.arrayContaining([
        [[33.45, -117.25], [33.5, -117.2]],
        [[33.45, -117.2], [33.5, -117.15]],
        [[33.5, -117.25], [33.55, -117.2]],
        [[33.5, -117.2], [33.55, -117.15]],
      ])
    );

    const excludedCell = heatmapCalls.find((props) => props.bounds[0][1] === -117.25);
    expect((excludedCell?.pathOptions as { fillColor?: string; fillOpacity?: number } | undefined)?.fillColor).toBe("#1f2937");
    expect((excludedCell?.pathOptions as { fillOpacity?: number } | undefined)?.fillOpacity).toBe(0.5);

    const searchableCells = heatmapCalls
      .filter((props) => (props.pathOptions as { fillColor?: string } | undefined)?.fillColor !== "#1f2937")
      .sort((a, b) => a.bounds[0][0] - b.bounds[0][0] || a.bounds[0][1] - b.bounds[0][1]);

    expect(searchableCells).toHaveLength(3);
    expect((searchableCells[0].pathOptions as { fillColor?: string; fillOpacity?: number }).fillColor).toBe("#bfdbfe");
    expect((searchableCells[0].pathOptions as { fillOpacity?: number }).fillOpacity).toBeCloseTo(0.1);
    expect((searchableCells[1].pathOptions as { fillColor?: string; fillOpacity?: number }).fillColor).toBe("#3b82f6");
    expect((searchableCells[1].pathOptions as { fillOpacity?: number }).fillOpacity).toBeCloseTo(0.3);
    expect((searchableCells[2].pathOptions as { fillColor?: string; fillOpacity?: number }).fillColor).toBe("#1e40af");
    expect((searchableCells[2].pathOptions as { fillOpacity?: number }).fillOpacity).toBeCloseTo(0.6);
  });

  it("computes probability heatmap stats from searchable positive values only", () => {
    expect(
      getProbabilityHeatmapStats(
        [0, 0.1, 0.3, 0.6],
        2,
        2,
        [
          [5, 2],
          [2, 2],
        ],
        [
          [false, true],
          [true, true],
        ]
      )
    ).toEqual({
      minPositive: 0.1,
      maxPositive: 0.6,
      positiveCount: 3,
      excludedCount: 1,
    });
  });

  it("uses a readable midpoint opacity when all searchable positive probabilities are equal", () => {
    render(
      <MapPanel
        {...defaultProps}
        setupStage="label_regions"
        selectedBounds={{ min_lat: 33.45, max_lat: 33.55, min_lon: -117.25, max_lon: -117.15 }}
        gridShape={[2, 2]}
        probabilityGrid={[0, 0.25, 0.25, 0.25]}
        showProbabilityHeatmap
      />
    );

    const searchableCells = mocks.rectangle.mock.calls
      .map(([props]) => props)
      .filter((props) => (props.pathOptions as { fillColor?: string } | undefined)?.fillColor === "#3b82f6");

    expect(searchableCells).toHaveLength(3);
    searchableCells.forEach((props) => {
      expect((props.pathOptions as { fillOpacity?: number }).fillOpacity).toBeCloseTo(0.35);
    });
  });

  it("detects excluded cells from either labels or searchable mask", () => {
    expect(
      isExcludedProbabilityCell(
        0,
        0,
        [
          [5, 2],
          [2, 2],
        ],
        undefined
      )
    ).toBe(true);

    expect(
      isExcludedProbabilityCell(
        0,
        1,
        undefined,
        [
          [true, false],
          [true, true],
        ]
      )
    ).toBe(true);

    expect(
      isExcludedProbabilityCell(
        1,
        1,
        [
          [2, 2],
          [2, 2],
        ],
        [
          [true, true],
          [true, true],
        ]
      )
    ).toBe(false);
  });

  it("disables Leaflet box zoom so shift-drag does not auto-zoom", () => {
    render(<MapPanel {...defaultProps} setupStage="label_regions" />);

    const mapContainerProps = mocks.mapContainer.mock.calls[0]?.[0];
    expect(mapContainerProps?.boxZoom).toBe(false);
  });

  it("disables probability-region shift-drag in review mode", () => {
    render(<MapPanel {...defaultProps} setupStage="review_probability_map" />);

    expect(bboxDrawerMock.props).toHaveLength(2);
    expect(bboxDrawerMock.props[1].enabled).toBe(false);
  });

  it("maps grid cells with row as latitude index and col as longitude index", () => {
    const bounds = {
      min_lat: 10,
      max_lat: 16,
      min_lon: 20,
      max_lon: 28,
    };

    expect(getGridCellBounds(bounds, [3, 4], [0, 0])).toEqual([[10, 20], [12, 22]]);
    expect(getGridCellBounds(bounds, [3, 4], [2, 3])).toEqual([[14, 26], [16, 28]]);
    expect(getGridCellBounds(bounds, [3, 4], [0, 1])).toEqual([[10, 22], [12, 24]]);
    expect(getGridCellBounds(bounds, [3, 4], [1, 0])).toEqual([[12, 20], [14, 22]]);
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
