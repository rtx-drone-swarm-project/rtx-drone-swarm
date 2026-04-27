import { MapContainer, Marker, Rectangle, TileLayer } from "react-leaflet";
import type { Bounds, SelectedDrone, Target, ValidDrone } from "../../types/mission";
import { boundsToLeaflet } from "../../utils/geo";
import MapBBoxDrawer from "./MapBBoxDrawer";
import MapControlStack from "./MapControlStack";
import MapRecenter from "./MapRecenter";
import { makeDroneIcon, makeTargetCircleIcon } from "./icons";

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
};

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
  onSelectArea
}: MapPanelProps) {
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
