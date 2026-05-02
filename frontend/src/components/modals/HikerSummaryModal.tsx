import { algorithmDisplayLabel, type Target } from "../../types/mission";

type HikerSummaryModalProps = {
  isOpen: boolean;
  onClose: () => void;
  targets: Target[];
  getHikerLabel: (targetId: string | number) => string;
  algorithm?: string;
  completionElapsedSeconds?: number;
};

export default function HikerSummaryModal({ isOpen, onClose, targets, getHikerLabel, algorithm, completionElapsedSeconds }: HikerSummaryModalProps) {
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
          {(algorithm || completionElapsedSeconds != null) && (
            <div className="mission-metrics">
              <div className="kv-grid">
                {algorithm && (
                  <>
                    <span>Algorithm</span>
                    <strong>{algorithmDisplayLabel(algorithm)}</strong>
                  </>
                )}
                {completionElapsedSeconds != null && completionElapsedSeconds > 0 && (
                  <>
                    <span>Mission Duration</span>
                    <strong>{completionElapsedSeconds}s</strong>
                  </>
                )}
                <span>Hikers Found</span>
                <strong>{targets.length}</strong>
              </div>
            </div>
          )}
          <p className="hiker-summary-intro">Final coordinates:</p>
          <ul className="hiker-summary-list">
            {targets.map((target) => (
              <li key={String(target.id)} className="hiker-summary-item">
                <div className="hiker-summary-label">{getHikerLabel(target.id)}</div>
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
