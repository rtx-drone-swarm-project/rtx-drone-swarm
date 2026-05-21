import { MapContainer, Marker, Polyline, Rectangle, TileLayer } from "react-leaflet";
import type { LeafletEvent, Marker as LeafletMarker } from "leaflet";
import type { AlgorithmOption, Bounds, PlacedHiker, ProbabilityRegionLabel, ProbabilityGridCell, SelectedDrone, Target, ValidDrone } from "../../types/mission";
import { PROBABILITY_REGION_CODE_BY_LABEL } from "../../types/mission";
import type { PmvHeatmapMessage } from "../../types/ws";
import { boundsToLeaflet } from "../../utils/geo";
import MapBBoxDrawer from "./MapBBoxDrawer";
import MapClickSelector from "./MapClickSelector";
import MapControlStack from "./MapControlStack";
import MapRecenter from "./MapRecenter";
import { makeCentroidIcon, makeDroneIcon, makePlacedHikerIcon, makeTargetCircleIcon } from "./icons";
import L from "leaflet";
import { useEffect, useMemo, useRef, useState } from "react";

type InterpolatedDroneProps = {
  drone: ValidDrone;
  label: string;
  setSelectedDrone: (value: SelectedDrone) => void;
};

function InterpolatedDrone({ drone, label, setSelectedDrone }: InterpolatedDroneProps) {
  const markerRef = useRef<LeafletMarker | null>(null);
  const requestRef = useRef<number>();
  
  const startPos = useRef<[number, number]>([drone.lat, drone.lon]);
  const startTime = useRef<number>(performance.now());
  
  const startHeading = useRef<number>(drone.heading || 0);
  const currentVisualHeading = useRef<number>(drone.heading || 0);

  const TICK_DURATION = 500;
  const ROTATION_DURATION = 450;
  const ANIMATION_DURATION = Math.max(TICK_DURATION, ROTATION_DURATION);

  const updateMarkerVisual = (lat: number, lon: number, heading: number) => {
    if (!markerRef.current) return;
    markerRef.current.setLatLng([lat, lon]);

    const el = markerRef.current.getElement();
    const iconInner = el?.querySelector(".drone-icon-wrap") as HTMLElement | null;
    iconInner?.style.setProperty("--drone-rotation", `${heading}deg`);
  };

  const animate = () => {
    const now = performance.now();
    const elapsed = now - startTime.current;

    const tPos = Math.min(elapsed / TICK_DURATION, 1.0);

    const linearRot = Math.min(elapsed / ROTATION_DURATION, 1.0);
    const tRot = 1 - (1 - linearRot) * (1 - linearRot);

    const currentLat = startPos.current[0] + (drone.lat - startPos.current[0]) * tPos;
    const currentLon = startPos.current[1] + (drone.lon - startPos.current[1]) * tPos;

    let diff = (drone.heading || 0) - startHeading.current;
    diff = ((diff + 180) % 360 + 360) % 360 - 180;

    const displayHeading = startHeading.current + (diff * tRot);
    currentVisualHeading.current = displayHeading;
    updateMarkerVisual(currentLat, currentLon, displayHeading);

    if (elapsed >= ANIMATION_DURATION) {
      const finalHeading = startHeading.current + diff;
      currentVisualHeading.current = finalHeading;
      updateMarkerVisual(drone.lat, drone.lon, finalHeading);
      requestRef.current = undefined;
      return;
    }

    requestRef.current = requestAnimationFrame(animate);
  };

  useEffect(() => {
    if (markerRef.current) {
      const currentOnScreen = markerRef.current.getLatLng();
      startPos.current = [currentOnScreen.lat, currentOnScreen.lng];
      startHeading.current = currentVisualHeading.current;
    }
    
    startTime.current = performance.now();
    requestRef.current = requestAnimationFrame(animate);
    
    return () => {
      if (requestRef.current) cancelAnimationFrame(requestRef.current);
    };
  }, [drone.lat, drone.lon, drone.heading]);

  return (
    <Marker
      ref={markerRef}
      position={startPos.current}
      icon={makeDroneIcon(label, drone.role, currentVisualHeading.current)}
      eventHandlers={{
        click: (e) => {
          L.DomEvent.stopPropagation(e);
          setSelectedDrone(drone);
        },
      }}
    />
  );
}

type MapPanelProps = {
  defaultCenter: [number, number];
  defaultZoom: number;
  mapCenter: [number, number] | null;
  selectedBounds: Bounds | null;
  gridShape?: [number, number] | number[];
  probabilityMapMode: boolean;
  probabilityMapReviewMode?: boolean;
  missionActive: boolean;
  validDrones: ValidDrone[];
  targets: Target[];
  placedHikers: PlacedHiker[];
  hikerPlacementEditable: boolean;
  hikerPlacementMode: boolean;
  getHikerLabel: (targetId: string | number) => string;
  getPlacedHikerLabel: (hiker: PlacedHiker, index: number) => string;
  setSelectedDrone: (value: SelectedDrone) => void;
  onSelectHiker: (hikerId: string) => void;
  onPlaceHiker: (lat: number, lon: number) => void;
  onMoveHiker: (hikerId: string, lat: number, lon: number) => void;
  onSelectArea: (bounds: Bounds) => void;
  onSelectTemporaryRegion: (bounds: Bounds) => void;
  temporaryRegionBounds: Bounds | null;
  temporaryRegionCells: ProbabilityGridCell[];
  operatorLabelGrid?: number[][];
  searchableMask?: boolean[][];
  showLabelledRegions: boolean;
  probabilityGrid?: number[];
  showProbabilityHeatmap: boolean;
  droneTrails?: Record<string, [number, number][]>;
  pmvHeatmap?: PmvHeatmapMessage | null;
  selectedAlgorithm?: AlgorithmOption;
};

const TRAIL_COLORS = ["#34d399", "#60a5fa", "#f472b6", "#fbbf24", "#a78bfa", "#22d3ee", "#fb7185", "#4ade80"];



function trailColorForIndex(idx: number): string {
  return TRAIL_COLORS[idx % TRAIL_COLORS.length];
}

const APPLIED_REGION_STYLES: Record<Exclude<ProbabilityRegionLabel, "normal">, {
  color: string;
  fillColor: string;
  fillOpacity: number;
}> = {
  very_unlikely: { color: "#7f1d1d", fillColor: "#7f1d1d", fillOpacity: 0.35 },
  unlikely: { color: "#b91c1c", fillColor: "#b91c1c", fillOpacity: 0.25 },
  likely: { color: "#15803d", fillColor: "#15803d", fillOpacity: 0.25 },
  very_likely: { color: "#14532d", fillColor: "#14532d", fillOpacity: 0.35 },
  excluded: { color: "#1f2937", fillColor: "#1f2937", fillOpacity: 0.5 },
};

function getAppliedRegionStyle(labelCode: number) {
  if (labelCode === PROBABILITY_REGION_CODE_BY_LABEL.normal) {
    return null;
  }

  if (labelCode === PROBABILITY_REGION_CODE_BY_LABEL.very_unlikely) {
    return APPLIED_REGION_STYLES.very_unlikely;
  }
  if (labelCode === PROBABILITY_REGION_CODE_BY_LABEL.unlikely) {
    return APPLIED_REGION_STYLES.unlikely;
  }
  if (labelCode === PROBABILITY_REGION_CODE_BY_LABEL.likely) {
    return APPLIED_REGION_STYLES.likely;
  }
  if (labelCode === PROBABILITY_REGION_CODE_BY_LABEL.very_likely) {
    return APPLIED_REGION_STYLES.very_likely;
  }
  if (labelCode === PROBABILITY_REGION_CODE_BY_LABEL.excluded) {
    return APPLIED_REGION_STYLES.excluded;
  }

  return null;
}

type ProbabilityHeatmapStats = {
  minPositive: number | null;
  maxPositive: number | null;
  positiveCount: number;
  excludedCount: number;
};

const EXCLUDED_HEATMAP_STYLE = {
  color: "#1f2937",
  fillColor: "#1f2937",
  fillOpacity: 0.5,
  weight: 0,
  opacity: 0,
};

const LOW_PROBABILITY_HEATMAP_COLOR = "#bfdbfe";
const MEDIUM_PROBABILITY_HEATMAP_COLOR = "#3b82f6";
const HIGH_PROBABILITY_HEATMAP_COLOR = "#1e40af";

export function isExcludedProbabilityCell(
  row: number,
  col: number,
  operatorLabelGrid?: number[][],
  searchableMask?: boolean[][]
) {
  const labelCode = operatorLabelGrid?.[row]?.[col];
  if (Number(labelCode) === PROBABILITY_REGION_CODE_BY_LABEL.excluded) {
    return true;
  }

  const searchable = searchableMask?.[row]?.[col];
  return searchable === false;
}

export function getProbabilityHeatmapStats(
  probabilityGrid: number[] | null,
  rows: number,
  cols: number,
  operatorLabelGrid?: number[][],
  searchableMask?: boolean[][]
): ProbabilityHeatmapStats {
  if (!probabilityGrid || rows <= 0 || cols <= 0) {
    return { minPositive: null, maxPositive: null, positiveCount: 0, excludedCount: 0 };
  }

  let minPositive = Number.POSITIVE_INFINITY;
  let maxPositive = Number.NEGATIVE_INFINITY;
  let positiveCount = 0;
  let excludedCount = 0;

  probabilityGrid.forEach((probability, flatIndex) => {
    const row = Math.floor(flatIndex / cols);
    const col = flatIndex % cols;
    if (isExcludedProbabilityCell(row, col, operatorLabelGrid, searchableMask)) {
      excludedCount += 1;
      return;
    }

    const numericProbability = Number(probability);
    if (!Number.isFinite(numericProbability) || numericProbability <= 0) {
      return;
    }

    positiveCount += 1;
    if (numericProbability < minPositive) {
      minPositive = numericProbability;
    }
    if (numericProbability > maxPositive) {
      maxPositive = numericProbability;
    }
  });

  if (positiveCount === 0) {
    return { minPositive: null, maxPositive: null, positiveCount: 0, excludedCount };
  }

  return { minPositive, maxPositive, positiveCount, excludedCount };
}

export function getProbabilityHeatmapStyle(probability: number, stats: ProbabilityHeatmapStats) {
  if (!(probability > 0) || stats.minPositive == null || stats.maxPositive == null) {
    return null;
  }

  const { minPositive, maxPositive } = stats;
  const displayRatio =
    maxPositive > minPositive
      ? Math.max(0, Math.min(1, (probability - minPositive) / (maxPositive - minPositive)))
      : 0.5;
  const fillOpacity = 0.1 + (displayRatio * 0.5);
  let fillColor = LOW_PROBABILITY_HEATMAP_COLOR;
  if (displayRatio >= 0.72) {
    fillColor = HIGH_PROBABILITY_HEATMAP_COLOR;
  } else if (displayRatio >= 0.34) {
    fillColor = MEDIUM_PROBABILITY_HEATMAP_COLOR;
  }

  return {
    color: fillColor,
    fillColor,
    fillOpacity,
    weight: 0,
    opacity: 0,
  };
}

export function getGridCellBounds(
  bounds: Bounds,
  gridShape: [number, number] | number[] | undefined,
  cell: ProbabilityGridCell
) {
  if (!gridShape || gridShape.length !== 2) return null;

  const rows = Number(gridShape[0]);
  const cols = Number(gridShape[1]);

  if (!Number.isFinite(rows) || !Number.isFinite(cols) || rows <= 0 || cols <= 0) {
    return null;
  }

  const [row, col] = cell;

  if (row < 0 || row >= rows || col < 0 || col >= cols) {
    return null;
  }

  const latStep = (bounds.max_lat - bounds.min_lat) / rows;
  const lonStep = (bounds.max_lon - bounds.min_lon) / cols;

  // Backend/UI probability-grid convention:
  // row = latitude index
  // col = longitude index
  const minLat = bounds.min_lat + row * latStep;
  const maxLat = bounds.min_lat + (row + 1) * latStep;

  const minLon = bounds.min_lon + col * lonStep;
  const maxLon = bounds.min_lon + (col + 1) * lonStep;

  return [
    [minLat, minLon],
    [maxLat, maxLon],
  ] as [[number, number], [number, number]];
}

function heatmapColor(intensity: number): string {
  const clamped = Math.max(0, Math.min(1, intensity));
  if (clamped < 0.5) {
    const t = clamped / 0.5;
    const r = Math.round(37 + (250 - 37) * t);
    const g = Math.round(99 + (204 - 99) * t);
    const b = Math.round(235 + (21 - 235) * t);
    return `rgb(${r}, ${g}, ${b})`;
  }
  const t = (clamped - 0.5) / 0.5;
  const r = Math.round(250 + (220 - 250) * t);
  const g = Math.round(204 + (38 - 204) * t);
  const b = Math.round(21 + (38 - 21) * t);
  return `rgb(${r}, ${g}, ${b})`;
}

export default function MapPanel({
  defaultCenter,
  defaultZoom,
  mapCenter,
  selectedBounds,
  gridShape,
  probabilityMapMode,
  probabilityMapReviewMode = false,
  missionActive,
  validDrones,
  targets,
  placedHikers,
  hikerPlacementEditable,
  hikerPlacementMode,
  getHikerLabel,
  getPlacedHikerLabel,
  setSelectedDrone,
  onSelectHiker,
  onPlaceHiker,
  onMoveHiker,
  onSelectArea,
  onSelectTemporaryRegion,
  temporaryRegionBounds,
  temporaryRegionCells,
  operatorLabelGrid,
  searchableMask,
  showLabelledRegions,
  probabilityGrid,
  showProbabilityHeatmap,
  droneTrails,
  pmvHeatmap,
  selectedAlgorithm
}: MapPanelProps) {
  const sweepActive = selectedAlgorithm === "sweep" && missionActive;
  const pmvActive = selectedAlgorithm === "pmv" && missionActive && !!pmvHeatmap;
  const [pmvHeatmapVisible, setPmvHeatmapVisible] = useState(true);
  const heatmapMissionKey = pmvHeatmap?.mission_id == null ? "" : String(pmvHeatmap.mission_id);
  const rectBounds = selectedBounds ? boundsToLeaflet(selectedBounds) : null;
  const temporaryRectBounds = temporaryRegionBounds ? boundsToLeaflet(temporaryRegionBounds) : null;
  const runtimeTargetIds = new Set(targets.map((target) => String(target.id)));
  const rows = Number(gridShape?.[0] ?? 0);
  const cols = Number(gridShape?.[1] ?? 0);
  const validProbabilityGrid =
    Array.isArray(probabilityGrid) && rows > 0 && cols > 0 && probabilityGrid.length === rows * cols
      ? probabilityGrid
      : null;
  const heatmapStats = getProbabilityHeatmapStats(
    validProbabilityGrid,
    rows,
    cols,
    operatorLabelGrid,
    searchableMask
  );
  const heatmapCells = useMemo(() => {
    if (!pmvActive || !pmvHeatmapVisible || !pmvHeatmap) return [];
    const { bounds, rows, cols, values, max_value: maxValue } = pmvHeatmap;
    if (rows <= 0 || cols <= 0 || values.length !== rows * cols || maxValue <= 0) return [];
    const latStep = (bounds.max_lat - bounds.min_lat) / rows;
    const lonStep = (bounds.max_lon - bounds.min_lon) / cols;
    return values.map((value, index) => {
      const row = Math.floor(index / cols);
      const col = index % cols;
      const intensity = value / maxValue;
      return {
        key: `pmv-heat-${row}-${col}`,
        bounds: [
          [bounds.min_lat + row * latStep, bounds.min_lon + col * lonStep],
          [bounds.min_lat + (row + 1) * latStep, bounds.min_lon + (col + 1) * lonStep]
        ] as [[number, number], [number, number]],
        intensity
      };
    });
  }, [pmvActive, pmvHeatmap, pmvHeatmapVisible]);

  useEffect(() => {
    setPmvHeatmapVisible(true);
  }, [heatmapMissionKey]);

  return (
    <div className={`map-wrap ${hikerPlacementMode ? "is-placing-hiker" : ""}`}>
      {pmvActive && (
        <label className="pmv-heatmap-toggle">
          <input
            type="checkbox"
            checked={pmvHeatmapVisible}
            onChange={(event) => setPmvHeatmapVisible(event.target.checked)}
          />
          <span>PMV heatmap</span>
        </label>
      )}
      <MapContainer center={defaultCenter} zoom={defaultZoom} zoomControl={false} className="leaflet-map">
        <MapRecenter center={mapCenter} />
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="&copy; OpenStreetMap contributors"
        />
        <MapControlStack drones={validDrones} />
        <MapClickSelector enabled={hikerPlacementMode && hikerPlacementEditable} onSelect={onPlaceHiker} />
        <MapBBoxDrawer
          enabled={!probabilityMapMode && !missionActive && !hikerPlacementMode}
          onBoundsDrawn={onSelectArea}
        />
        <MapBBoxDrawer
          enabled={probabilityMapMode && !probabilityMapReviewMode}
          onBoundsDrawn={onSelectTemporaryRegion}
          pathOptions={{ color: "#f59e0b", fillOpacity: 0.06, dashArray: "10 6", weight: 2 }}
        />

        {rectBounds && (
          <Rectangle
            bounds={rectBounds}
            pathOptions={{ color: "#3b82f6", fillOpacity: 0.08, dashArray: "8 8", weight: 2 }}
          />
        )}

        {temporaryRectBounds && (
          <Rectangle
            bounds={temporaryRectBounds}
            pathOptions={{ color: "#f59e0b", fillOpacity: 0.06, dashArray: "10 6", weight: 2 }}
          />
        )}

        {probabilityMapMode &&
          showLabelledRegions &&
          selectedBounds &&
          Array.isArray(operatorLabelGrid) &&
          operatorLabelGrid.flatMap((labelRow, row) =>
            Array.isArray(labelRow)
              ? labelRow.map((labelCode, col) => {
                  const pathStyle = getAppliedRegionStyle(Number(labelCode));
                  if (!pathStyle) return null;
                  const cellBounds = getGridCellBounds(selectedBounds, gridShape, [row, col]);
                  if (!cellBounds) return null;
                  return (
                    <Rectangle
                      key={`applied-cell-${row}-${col}`}
                      bounds={cellBounds}
                      pathOptions={{
                        ...pathStyle,
                        weight: 0.4,
                        opacity: 0.35,
                      }}
                    />
                  );
                })
              : []
          )}

        {probabilityMapMode &&
          showProbabilityHeatmap &&
          selectedBounds &&
          validProbabilityGrid &&
          validProbabilityGrid.map((probability, flatIndex) => {
            const row = Math.floor(flatIndex / cols);
            const col = flatIndex % cols;
            const cellBounds = getGridCellBounds(selectedBounds, gridShape, [row, col]);
            if (!cellBounds) return null;

            if (isExcludedProbabilityCell(row, col, operatorLabelGrid, searchableMask)) {
              return (
                <Rectangle
                  key={`probability-cell-excluded-${row}-${col}`}
                  bounds={cellBounds}
                  pathOptions={EXCLUDED_HEATMAP_STYLE}
                />
              );
            }

            const numericProbability = Number(probability);
            const pathStyle = getProbabilityHeatmapStyle(numericProbability, heatmapStats);
            if (!pathStyle) return null;

            return (
              <Rectangle
                key={`probability-cell-${row}-${col}`}
                bounds={cellBounds}
                pathOptions={pathStyle}
              />
            );
          })}

        {selectedBounds && temporaryRegionCells.map((cell) => {
          const cellBounds = getGridCellBounds(selectedBounds, gridShape, cell);
          if (!cellBounds) return null;
          return (
            <Rectangle
              key={`temp-cell-${cell[0]}-${cell[1]}`}
              bounds={cellBounds}
              pathOptions={{
                color: "#38bdf8",
                fillColor: "#60a5fa",
                fillOpacity: 0.24,
                dashArray: "6 4",
                weight: 1.6,
              }}
            />
          );
        })}

        {heatmapCells.map((cell) => (
          <Rectangle
            key={cell.key}
            bounds={cell.bounds}
            interactive={false}
            pathOptions={{
              color: heatmapColor(cell.intensity),
              fillColor: heatmapColor(cell.intensity),
              fillOpacity: 0.08 + Math.min(0.42, cell.intensity * 0.42),
              opacity: 0.18,
              weight: 0,
              className: "pmv-heatmap-cell"
            }}
          />
        ))}

        {droneTrails &&
          validDrones.map((drone, idx) => {
            const trail = droneTrails[String(drone.id)];
            if (!trail || trail.length < 2) return null;
            const isSweepTrail = selectedAlgorithm === "sweep";
            return (
              <Polyline
                key={`trail-${String(drone.id)}`}
                positions={trail}
                pathOptions={{
                  color: trailColorForIndex(idx),
                  weight: isSweepTrail ? 4 : 2,
                  opacity: isSweepTrail ? 0.92 : 0.6,
                  dashArray: isSweepTrail ? undefined : "4 6",
                  className: isSweepTrail ? "sweep-drone-trail" : "drone-trail"
                }}
              />
            );
          })}

        {sweepActive &&
          validDrones.map((drone, idx) => {
            const centroid = drone.sweep_centroid;
            if (!centroid) return null;
            const rawId = String(drone.id);
            const label = rawId.startsWith("D") ? rawId : `D${rawId || idx + 1}`;
            return (
              <Marker
                key={`centroid-${rawId}`}
                position={centroid}
                icon={makeCentroidIcon(`${label} centroid`, drone.sweep_phase)}
                interactive={false}
              />
            );
          })}

        {validDrones.map((drone, idx) => {
          const rawId = String(drone.id);
          const label = rawId.startsWith("D") ? rawId : `D${rawId || idx + 1}`;
          return (
            <InterpolatedDrone
              key={`${String(drone.id)}-${drone.role ?? "normal"}`}
              drone={drone}
              label={label}
              setSelectedDrone={setSelectedDrone}
            />
          );
        })}

        {targets.map((target) => {
          const label = getHikerLabel(target.id);
          return (
            <Marker
              key={`${target.id}-${target.status ?? "wandering"}`}
              position={[target.lat, target.lon]}
              icon={makeTargetCircleIcon(label, target.status)}
            />
          );
        })}

        {placedHikers.map((hiker, index) => {
          if (runtimeTargetIds.has(String(hiker.id))) return null;
          const label = getPlacedHikerLabel(hiker, index);
          return (
            <Marker
              key={hiker.id}
              position={[hiker.lat, hiker.lon]}
              icon={makePlacedHikerIcon(label, hiker.movement, !hikerPlacementEditable)}
              draggable={hikerPlacementEditable}
              eventHandlers={{
                click: () => onSelectHiker(hiker.id),
                dragend: (event: LeafletEvent) => {
                  const marker = event.target as LeafletMarker;
                  const latLng = marker.getLatLng();
                  onMoveHiker(hiker.id, latLng.lat, latLng.lng);
                }
              }}
            />
          );
        })}
      </MapContainer>
    </div>
  );
}
