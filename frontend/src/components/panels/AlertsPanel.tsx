import type { Bounds } from "../../types/mission";
import CollapsibleSection from "../common/CollapsibleSection";
import SearchingLabel from "../common/SearchingLabel";

type AlertsPanelProps = {
  missionComplete: boolean;
  missionStatus: string;
  selectedBounds: Bounds | null;
  wsConnected: boolean;
};

export default function AlertsPanel({
  missionComplete,
  missionStatus,
  selectedBounds,
  wsConnected
}: AlertsPanelProps) {
  const missionChip = missionComplete ? (
    <div className="alert-chip complete">
      <span className="alert-icon">&#x2705;</span>
      <div>
        <div className="alert-title">Mission status</div>
        <div className="alert-sub">Mission complete — all hikers found, all drones recalled.</div>
      </div>
    </div>
  ) : missionStatus === "searching" ? (
    <div className="alert-chip info">
      <span className="alert-icon search-pulse-icon">&#x1F50D;</span>
      <div>
        <div className="alert-title">Mission status</div>
        <div className="alert-sub">
          <SearchingLabel text="Search in progress — searching selected area." />
        </div>
      </div>
    </div>
  ) : missionStatus === "search_complete" ? (
    <div className="alert-chip info">
      <span className="alert-icon search-pulse-icon">&#x1F50D;</span>
      <div>
        <div className="alert-title">Mission status</div>
        <div className="alert-sub">
          <SearchingLabel text="Search complete — all hikers found, awaiting drone instruction." />
        </div>
      </div>
    </div>
  ) : missionStatus === "recalling" ? (
    <div className="alert-chip info">
      <span className="alert-icon search-pulse-icon">&#x1F50D;</span>
      <div>
        <div className="alert-title">Mission status</div>
        <div className="alert-sub">
          <SearchingLabel text="Recalling — all hikers found, recalling drones." />
        </div>
      </div>
    </div>
  ) : missionStatus === "paused" ? (
    <div className="alert-chip paused">
      <span className="alert-icon">&#x1F6D1;</span>
      <div>
        <div className="alert-title">Mission status</div>
        <div className="alert-sub">Paused — search paused by operator.</div>
      </div>
    </div>
  ) : selectedBounds ? (
    <div className="alert-chip warning">
      <span className="alert-icon">&#x26A0;</span>
      <div>
        <div className="alert-title">Mission status</div>
        <div className="alert-sub">Idle — 100km&#xB2; area selected. Ready to start.</div>
      </div>
    </div>
  ) : (
    <div className="alert-chip info">
      <span className="alert-icon">&#x2139;</span>
      <div>
        <div className="alert-title">Mission status</div>
        <div className="alert-sub">Idle — click the map to select a search area.</div>
      </div>
    </div>
  );

  return (
    <CollapsibleSection title="Status">
      <div className="stack-list">
        {missionChip}

        <div className={`alert-chip ${wsConnected ? "ok" : "error"}`}>
          <span className="alert-icon">{wsConnected ? "\u{1F7E2}" : "\u{1F534}"}</span>
          <div>
            <div className="alert-title">WebSocket</div>
            <div className="alert-sub">{wsConnected ? "Connected" : "Disconnected"}</div>
          </div>
        </div>
      </div>
    </CollapsibleSection>
  );
}
