import { MapContainer, Marker, Polyline, Rectangle, TileLayer } from "react-leaflet";
import type { AlgorithmOption, Bounds, SelectedDrone, Target, ValidDrone } from "../../types/mission";
import { boundsToLeaflet } from "../../utils/geo";
import MapBBoxDrawer from "./MapBBoxDrawer";
import MapControlStack from "./MapControlStack";
import MapRecenter from "./MapRecenter";
import { makeCentroidIcon, makeDroneIcon, makeTargetCircleIcon } from "./icons";

type MapPanelProps = {
  defaultCenter: [number, number];
  defaultZoom: number;
  mapCenter: [number, number] | null;
  selectedBounds: Bounds | null;
  missionActive: boolean;
  validDrones: ValidDrone[];
  targets: Target[];
  getHikerLabel: (targetId: string | number) => string;
  setSelectedDrone: (value: SelectedDrone) => void;
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
  getHikerLabel,
  setSelectedDrone,
  onSelectArea,
  droneTrails,
  selectedAlgorithm
}: MapPanelProps) {
  const sweepActive = selectedAlgorithm === "sweep" && missionActive;
  const rectBounds = selectedBounds ? boundsToLeaflet(selectedBounds) : null;

  return (
    <div className="map-wrap">
      <MapContainer center={defaultCenter} zoom={defaultZoom} zoomControl={false} className="leaflet-map">
        <MapRecenter center={mapCenter} />
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="&copy; OpenStreetMap contributors"
        />
        <MapControlStack drones={validDrones} />
        <MapBBoxDrawer
          enabled={!missionActive}
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
            <Marker
              key={`${String(drone.id)}-${drone.role ?? "normal"}`}
              position={[drone.lat, drone.lon]}
              icon={makeDroneIcon(label, drone.role, drone.heading)}
              eventHandlers={{
                click: () => setSelectedDrone(drone)
              }}
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
      </MapContainer>
    </div>
  );
}
