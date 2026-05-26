import type { MissionMetrics, Target } from "../../types/mission";
import { formatSeconds } from "../../utils/format";

type SearchSummaryModalProps = {
  isOpen: boolean;
  onClose: () => void;
  targets: Target[];
  getHikerLabel: (targetId: string | number) => string;
  onRecall: () => void;
  completionElapsedSeconds?: number;
  metrics?: MissionMetrics | null;
};

export default function SearchSummaryModal({
  isOpen,
  onClose,
  targets,
  getHikerLabel,
  onRecall,
  completionElapsedSeconds,
  metrics
}: SearchSummaryModalProps) {
  if (!isOpen || !targets.length) return null;

  const durationSeconds = metrics?.completion_elapsed_seconds ?? completionElapsedSeconds;
  const targetsFound = metrics?.targets_found ?? targets.length;
  const targetsTotal = metrics?.targets_total ?? targets.length;

  return (
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <div
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Search summary"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2>Search Complete - Hikers Found</h2>
          <button type="button" className="icon-close" onClick={onClose} aria-label="Close dialog">
            &#x2715;
          </button>
        </div>

        <div className="search-summary-body">
          {(durationSeconds != null || metrics) && (
            <div className="mission-metrics">
              <div className="kv-grid">
                {durationSeconds != null && durationSeconds > 0 && (
                  <>
                    <span>Mission Duration</span>
                    <strong>{formatSeconds(durationSeconds)}</strong>
                  </>
                )}
                <span>Hikers Found</span>
                <strong>{targetsFound}/{targetsTotal}</strong>
                {metrics?.coverage_pct != null && (
                  <>
                    <span>Coverage</span>
                    <strong>{metrics.coverage_pct}%</strong>
                  </>
                )}
                {metrics?.first_find_seconds != null && (
                  <>
                    <span>First Find</span>
                    <strong>{formatSeconds(metrics.first_find_seconds)}</strong>
                  </>
                )}
                {metrics?.last_find_seconds != null && (
                  <>
                    <span>Last Find</span>
                    <strong>{formatSeconds(metrics.last_find_seconds)}</strong>
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
        </div>
      </div>
    </div>
  );
}
