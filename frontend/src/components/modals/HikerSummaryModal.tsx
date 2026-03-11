import type { Target } from "../../types/mission";

type HikerSummaryModalProps = {
  isOpen: boolean;
  onClose: () => void;
  targets: Target[];
};

export default function HikerSummaryModal({ isOpen, onClose, targets }: HikerSummaryModalProps) {
  if (!isOpen || !targets.length) return null;

  return (
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <div
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Hiker summary"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2>Mission Complete - Hikers Found</h2>
          <button type="button" className="icon-close" onClick={onClose} aria-label="Close dialog">
            &#x2715;
          </button>
        </div>

        <div className="hiker-summary-body">
          <p className="hiker-summary-intro">
            All hikers in the selected search area have been found. Final coordinates:
          </p>
          <ul className="hiker-summary-list">
            {targets.map((target, idx) => (
              <li key={`${target.id}-${idx}`} className="hiker-summary-item">
                <div className="hiker-summary-label">Hiker {idx + 1}</div>
                <div className="hiker-summary-coords">
                  {target.lat.toFixed(6)}, {target.lon.toFixed(6)}
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="hiker-summary-footer">
          <button type="button" className="action-btn start" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
