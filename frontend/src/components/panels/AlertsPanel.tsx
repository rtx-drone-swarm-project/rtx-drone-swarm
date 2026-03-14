import type { Bounds, MissionStatus } from "../../types/mission";
import CollapsibleSection from "../common/CollapsibleSection";
import SearchingLabel from "../common/SearchingLabel";

type AlertsPanelProps = {
  missionComplete: boolean;
  normalizedSearchStatus: MissionStatus;
  selectedBounds: Bounds | null;
  wsConnected: boolean;
  alerts: string[];
};

export default function AlertsPanel({
  missionComplete,
  normalizedSearchStatus,
  selectedBounds,
  wsConnected,
  alerts
}: AlertsPanelProps) {
  return (
    <CollapsibleSection title="Alerts">
      <div className="stack-list">
        {missionComplete ? (
          <div className="alert-chip complete">
            <span className="alert-icon">&#x2705;</span>
            <div>
              <div className="alert-title">Mission completed</div>
              <div className="alert-sub">All hikers found. Search at 100%.</div>
            </div>
          </div>
        ) : normalizedSearchStatus === "stopped" ? (
          <div className="alert-chip stopped">
            <span className="alert-icon">&#x1F6D1;</span>
            <div>
              <div className="alert-title">Mission stopped</div>
              <div className="alert-sub">Search halted by operator.</div>
            </div>
          </div>
        ) : normalizedSearchStatus === "running" ? (
          <div className="alert-chip info">
            <span className="alert-icon search-pulse-icon">&#x1F50D;</span>
            <div>
              <div className="alert-title">Mission in progress</div>
              <div className="alert-sub">
                <SearchingLabel text="Searching selected area" />
              </div>
            </div>
          </div>
        ) : selectedBounds ? (
          <div className="alert-chip warning">
            <span className="alert-icon">&#x26A0;</span>
            <div>
              <div className="alert-title">Marker placed</div>
              <div className="alert-sub">100km&#xB2; search area selected</div>
            </div>
          </div>
        ) : null}

        <div className={`alert-chip ${wsConnected ? "ok" : "error"}`}>
          <span className="alert-icon">{wsConnected ? "\u{1F7E2}" : "\u{1F534}"}</span>
          <span>WebSocket {wsConnected ? "connected" : "disconnected"}</span>
        </div>

        <div className="alert-log-scroll">
          {alerts.map((alert, idx) => (
            <div key={`${alert}-${idx}`} className="alert-log">
              {alert}
            </div>
          ))}
        </div>
      </div>
    </CollapsibleSection>
  );
}
