import { MapContainer, Marker, Polyline, Rectangle, TileLayer } from "react-leaflet";
import type { LeafletEvent, Marker as LeafletMarker } from "leaflet";
import type { AlgorithmOption, Bounds, PlacedHiker, ProbabilityGridCell, SelectedDrone, Target, ValidDrone } from "../../types/mission";
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
  droneTrails?: Record<string, [number, number][]>;
  pmvHeatmap?: PmvHeatmapMessage | null;
  selectedAlgorithm?: AlgorithmOption;
};

const TRAIL_COLORS = ["#34d399", "#60a5fa", "#f472b6", "#fbbf24", "#a78bfa", "#22d3ee", "#fb7185", "#4ade80"];



function trailColorForIndex(idx: number): string {
  return TRAIL_COLORS[idx % TRAIL_COLORS.length];
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
          enabled={probabilityMapMode}
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

        {selectedBounds && temporaryRegionCells.map((cell) => {
          const cellBounds = getGridCellBounds(selectedBounds, gridShape, cell);
          if (!cellBounds) return null;
          return (
            <Rectangle
              key={`temp-cell-${cell[0]}-${cell[1]}`}
              bounds={cellBounds}
              pathOptions={{ color: "#f97316", fillColor: "#f97316", fillOpacity: 0.28, weight: 1 }}
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
