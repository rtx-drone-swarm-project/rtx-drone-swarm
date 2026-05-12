import { MapContainer, Marker, Polyline, Rectangle, TileLayer } from "react-leaflet";
import type { LeafletEvent, Marker as LeafletMarker } from "leaflet";
import type { AlgorithmOption, Bounds, PlacedHiker, SelectedDrone, Target, ValidDrone } from "../../types/mission";
import { boundsToLeaflet } from "../../utils/geo";
import MapBBoxDrawer from "./MapBBoxDrawer";
import MapClickSelector from "./MapClickSelector";
import MapControlStack from "./MapControlStack";
import MapRecenter from "./MapRecenter";
import { makeCentroidIcon, makeDroneIcon, makePlacedHikerIcon, makeTargetCircleIcon } from "./icons";
import L from "leaflet";
import { useEffect, useRef } from "react";

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
  onSelectArea: (lat: number, lon: number, bounds: Bounds) => void;
  droneTrails?: Record<string, [number, number][]>;
  selectedAlgorithm?: AlgorithmOption;
};

const TRAIL_COLORS = ["#34d399", "#60a5fa", "#f472b6", "#fbbf24", "#a78bfa", "#22d3ee", "#fb7185", "#4ade80"];



function trailColorForIndex(idx: number): string {
  return TRAIL_COLORS[idx % TRAIL_COLORS.length];
}

export default function MapPanel({
  defaultCenter,
  defaultZoom,
  mapCenter,
  selectedBounds,
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
  droneTrails,
  selectedAlgorithm
}: MapPanelProps) {
  const sweepActive = selectedAlgorithm === "sweep" && missionActive;
  const rectBounds = selectedBounds ? boundsToLeaflet(selectedBounds) : null;
  const runtimeTargetIds = new Set(targets.map((target) => String(target.id)));

  return (
    <div className={`map-wrap ${hikerPlacementMode ? "is-placing-hiker" : ""}`}>
      <MapContainer center={defaultCenter} zoom={defaultZoom} zoomControl={false} className="leaflet-map">
        <MapRecenter center={mapCenter} />
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="&copy; OpenStreetMap contributors"
        />
        <MapControlStack drones={validDrones} />
        <MapClickSelector enabled={hikerPlacementMode && hikerPlacementEditable} onSelect={onPlaceHiker} />
        <MapBBoxDrawer
          enabled={!missionActive && !hikerPlacementMode}
          onBoundsDrawn={(drawnBounds) => {
            const centerLat = (drawnBounds.min_lat + drawnBounds.max_lat) / 2;
            const centerLon = (drawnBounds.min_lon + drawnBounds.max_lon) / 2;
            onSelectArea(centerLat, centerLon, drawnBounds);
          }}
        />

        {rectBounds && (
          <Rectangle
            bounds={rectBounds}
            pathOptions={{ color: "#3b82f6", fillOpacity: 0.08, dashArray: "8 8", weight: 2 }}
          />
        )}

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
