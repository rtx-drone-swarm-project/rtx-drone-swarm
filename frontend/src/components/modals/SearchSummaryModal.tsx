import type { MissionMetrics, Target } from "../../types/mission";

const ALGORITHM_LABELS: Record<string, string> = {
  voronoi: "Voronoi (Lloyd's)",
  apf: "APF (Potential Fields)",
  sweep: "Sweep (Voronoi + Lawnmower)"
};

type SearchSummaryModalProps = {
  isOpen: boolean;
  onClose: () => void;
  targets: Target[];
  getHikerLabel: (targetId: string | number) => string;
  onRecall: () => void;
  onReset: () => void;
  algorithm?: string;
  completionElapsedSeconds?: number;
  metrics?: MissionMetrics | null;
};

export default function SearchSummaryModal({ isOpen, onClose, targets, getHikerLabel, onRecall, onReset, algorithm, completionElapsedSeconds, metrics }: SearchSummaryModalProps) {
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
          {(algorithm || completionElapsedSeconds != null || metrics) && (
            <div className="mission-metrics">
              <div className="kv-grid">
                {algorithm && (
                  <>
                    <span>Algorithm</span>
                    <strong>{ALGORITHM_LABELS[algorithm] ?? algorithm}</strong>
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
                {metrics?.coverage_pct != null && (
                  <>
                    <span>Coverage</span>
                    <strong>{metrics.coverage_pct}%</strong>
                  </>
                )}
                {metrics?.first_find_seconds != null && (
                  <>
                    <span>First Find</span>
                    <strong>{metrics.first_find_seconds}s</strong>
                  </>
                )}
                {metrics?.avg_find_seconds != null && (
                  <>
                    <span>Avg Find</span>
                    <strong>{metrics.avg_find_seconds}s</strong>
                  </>
                )}
              </div>
            </div>
          )}
          <p className="search-summary-intro">Final coordinates:</p>
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
