import type { SelectedDrone } from "../../types/mission";

type DroneModalProps = {
  drone: SelectedDrone;
  onClose: () => void;
};

export default function DroneModal({ drone, onClose }: DroneModalProps) {
  if (!drone) return null;

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
          <h2>Drone {drone.id} - Live Feed</h2>
          <button type="button" className="icon-close" onClick={onClose} aria-label="Close dialog">
            &#x2715;
          </button>
        </div>

        <div className="modal-video-placeholder">
          <span className="camera-emoji">&#x1F4F9;</span>
          <div>Drone Camera Feed</div>
          <small>Live view from Drone {drone.id}</small>
        </div>

        <div className="modal-grid">
          <div>
            <label>Altitude</label>
            <strong>{Math.floor(Math.random() * 500 + 100)}m</strong>
          </div>
          <div>
            <label>Speed</label>
            <strong>{Math.floor(Math.random() * 50 + 20)} km/h</strong>
          </div>
          <div>
            <label>Battery</label>
            <strong>{drone.battery}</strong>
          </div>
          <div>
            <label>Status</label>
            <strong className="success">Active</strong>
          </div>
        </div>
      </div>
    </div>
  );
}
