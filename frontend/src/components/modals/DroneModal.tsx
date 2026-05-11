import type { SelectedDrone } from "../../types/mission";

type DroneModalProps = {
  drone: SelectedDrone;
  onClose: () => void;
};

function formatNumber(value?: number | null, digits = 0) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  return value.toFixed(digits);
}

function formatMetric(value: number | null | undefined, unit: string, digits = 0) {
  const formatted = formatNumber(value, digits);
  return formatted === "--" ? formatted : `${formatted} ${unit}`;
}

function formatDroneStatus(drone: NonNullable<SelectedDrone>) {
  const armed = drone.armed ? "ARMED" : "DISARMED";
  if (typeof drone.status === "string" && drone.status.trim().length > 0) {
    return armed + ` / ${drone.status.toUpperCase()}`;
  }
  return armed + " / IDLE";
}

export default function DroneModal({ drone, onClose }: DroneModalProps) {
  if (!drone) return null;

  const label = `Drone ${drone.id}`;
  const roleText = drone.role ? drone.role.toUpperCase() : "SEARCH";
  const telemetrySource = drone.telemetry_source ? drone.telemetry_source.toUpperCase() : "UNKNOWN";
  const statusClass = drone.armed ? "success" : "warning-text";
  const assignment =
    typeof drone.target_lat === "number" && typeof drone.target_lon === "number"
      ? `${drone.target_lat.toFixed(4)}, ${drone.target_lon.toFixed(4)}`
      : "No assignment";

  return (
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <div
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-label={`Drone ${drone.id} details`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <h2>{label}</h2>
            <p className="modal-subtitle">
              {roleText} · {telemetrySource}
            </p>
          </div>
          <button type="button" className="icon-close" onClick={onClose} aria-label="Close dialog">
            &#x2715;
          </button>
        </div>

        <div className="modal-banner">
          <div className="modal-banner-label">Drone Name</div>
          <div className="modal-banner-value">{label}</div>
          <div className={`modal-banner-status ${statusClass}`}>{formatDroneStatus(drone)}</div>
        </div>

        <div className="modal-grid">
          <div>
            <label>Altitude</label>
            <strong>{formatMetric(drone.alt, "m")}</strong>
          </div>
          <div>
            <label>Speed</label>
            <strong>{formatMetric(drone.groundspeed, "m/s", 1)}</strong>
          </div>
          <div>
            <label>Status</label>
            <strong className={statusClass}>{formatDroneStatus(drone)}</strong>
          </div>
          <div>
            <label>Coordinates</label>
            <strong>{`${drone.lat.toFixed(4)}, ${drone.lon.toFixed(4)}`}</strong>
          </div>
          <div>
            <label>Assigned Target</label>
            <strong>{assignment}</strong>
          </div>
        </div>
      </div>
    </div>
  );
}
