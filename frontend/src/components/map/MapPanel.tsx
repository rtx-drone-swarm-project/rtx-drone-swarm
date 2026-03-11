import { MapContainer, Marker, Rectangle, TileLayer, Tooltip } from "react-leaflet";
import type { Bounds, SelectedDrone, Target, ValidDrone } from "../../types/mission";
import { boundsToLeaflet, fixedAreaBounds } from "../../utils/geo";
import MapClickSelector from "./MapClickSelector";
import MapRecenter from "./MapRecenter";
import { makeDroneIcon, makeTargetCircleIcon, makeTargetTriangleIcon } from "./icons";

type MapPanelProps = {
  defaultCenter: [number, number];
  defaultZoom: number;
  mapCenter: [number, number] | null;
  selectedBounds: Bounds | null;
  missionActive: boolean;
  validDrones: ValidDrone[];
  targets: Target[];
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
  setSelectedDrone,
  onSelectArea
}: MapPanelProps) {
  const rectBounds = selectedBounds ? boundsToLeaflet(selectedBounds) : null;

  return (
    <div className="map-wrap">
      <MapContainer center={defaultCenter} zoom={defaultZoom} zoomControl className="leaflet-map">
        <MapRecenter center={mapCenter} />
        <TileLayer
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          attribution="&copy; OpenStreetMap contributors"
        />
        <MapClickSelector
          enabled={!missionActive}
          onSelect={(lat, lon) => {
            onSelectArea(lat, lon, fixedAreaBounds(lat, lon));
          }}
        />

        {rectBounds && (
          <Rectangle
            bounds={rectBounds}
            pathOptions={{ color: "#3b82f6", fillOpacity: 0.08, dashArray: "8 8", weight: 2 }}
          />
        )}

        {validDrones.map((drone, idx) => {
          const label = `D${typeof drone.id === "number" ? drone.id : idx + 1}`;
          return (
            <Marker
              key={`${String(drone.id)}-${drone.role ?? "normal"}`}
              position={[drone.lat, drone.lon]}
              icon={makeDroneIcon(label, drone.role)}
              eventHandlers={{
                click: () =>
                  setSelectedDrone({
                    id: drone.id,
                    battery:
                      typeof drone.battery_remaining === "number"
                        ? `${Math.round(drone.battery_remaining)}%`
                        : "--"
                  })
              }}
            >
              <Tooltip>{`Drone ${drone.id}${drone.role ? ` (${drone.role})` : ""}`}</Tooltip>
            </Marker>
          );
        })}

        {targets.map((target) => {
          const isFoundOrConfirming = target.status === "found" || target.status === "confirming";
          return (
            <Marker
              key={`${target.id}-${target.status ?? "wandering"}`}
              position={[target.lat, target.lon]}
              icon={isFoundOrConfirming ? makeTargetTriangleIcon() : makeTargetCircleIcon()}
            >
              <Tooltip>
                {target.status === "found"
                  ? `Found Hiker ${target.id}`
                  : target.status === "confirming"
                    ? `Confirming Hiker ${target.id}`
                    : target.status === "wandering"
                      ? `Wandering Hiker ${target.id}`
                      : `Target ${target.id}`}
              </Tooltip>
            </Marker>
          );
        })}
      </MapContainer>
    </div>
  );
}
