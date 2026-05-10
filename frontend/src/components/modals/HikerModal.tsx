import type { HikerMovement, PlacedHiker } from "../../types/mission";

type HikerModalProps = {
  hiker: PlacedHiker | null;
  label: string;
  editable: boolean;
  onMovementChange: (movement: HikerMovement) => void;
  onClose: () => void;
};

export default function HikerModal({ hiker, label, editable, onMovementChange, onClose }: HikerModalProps) {
  if (!hiker) return null;

  return (
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <div
        className={`modal-panel hiker-modal-panel ${editable ? "" : "is-disabled"}`}
        role="dialog"
        aria-modal="true"
        aria-label={`${label} details`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <h2>{label}</h2>
            <p className="modal-subtitle">{editable ? "PLACEMENT" : "MISSION LOCKED"}</p>
          </div>
          <button type="button" className="icon-close" onClick={onClose} aria-label="Close dialog">
            &#x2715;
          </button>
        </div>

        <div className="modal-banner">
          <div className="modal-banner-label">Hiker Name</div>
          <div className="modal-banner-value">{label}</div>
          <div className={`modal-banner-status ${hiker.movement === "moving" ? "warning-text" : "success"}`}>
            {hiker.movement === "moving" ? "MOVING" : "STATIONARY"}
          </div>
        </div>

        <div className="modal-grid">
          <div>
            <label>Movement</label>
            <div className="segmented-control" aria-label="Hiker movement">
              <button
                type="button"
                className={hiker.movement === "stationary" ? "active" : ""}
                onClick={() => onMovementChange("stationary")}
                disabled={!editable}
              >
                Stationary
              </button>
              <button
                type="button"
                className={hiker.movement === "moving" ? "active" : ""}
                onClick={() => onMovementChange("moving")}
                disabled={!editable}
              >
                Moving
              </button>
            </div>
          </div>
          <div>
            <label>Coordinates</label>
            <strong>{`${hiker.lat.toFixed(6)}, ${hiker.lon.toFixed(6)}`}</strong>
          </div>
        </div>
      </div>
    </div>
  );
}
