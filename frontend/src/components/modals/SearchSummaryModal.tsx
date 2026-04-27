import type { Target } from "../../types/mission";

type SearchSummaryModalProps = {
  isOpen: boolean;
  onClose: () => void;
  targets: Target[];
  getHikerLabel: (targetId: string | number) => string;
  onRecall: () => void;
  onReset: () => void;
};

export default function SearchSummaryModal({ isOpen, onClose, targets, getHikerLabel, onRecall, onReset }: SearchSummaryModalProps) {
  if (!isOpen || !targets.length) return null;

  return (
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <div
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-label= "Search summary"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2>Search Complete - Hikers Found</h2>
          <button type="button" className="icon-close" onClick={onClose} aria-label="Close dialog">
            &#x2715;
          </button>
        </div>

        <div className="search-summary-body">
          <p className="search-summary-intro">
            All hikers in the selected search area have been found. Final coordinates:
          </p>
          <ul className="search-summary-list">
            {targets.map((target) => (
              <li key={String(target.id)} className="search-summary-item">
                <div className="search-summary-label">{getHikerLabel(target.id)}</div>
                <div className="search-summary-coords">
                  {target.lat.toFixed(6)}, {target.lon.toFixed(6)}
                </div>
              </li>
            ))}
          </ul>
        </div>

        <div className="search-summary-footer">
          <button type="button" className="action-btn start" onClick={() => { onRecall(); onClose(); }}>Recall Drones</button>
          <button type="button" className="action-btn start" onClick={() => { onReset(); onClose(); }}>Reset Simulation</button>
        </div>
      </div>
    </div>
  );
}
