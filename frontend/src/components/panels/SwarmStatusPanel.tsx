import { formatElapsed, statusLabel } from "../../utils/format";
import CollapsibleSection from "../common/CollapsibleSection";
import SearchingLabel from "../common/SearchingLabel";

type SwarmStatusPanelProps = {
  elapsedSeconds: number;
  telemetryCount: number;
  validDroneCount: number;
  missionActive: boolean;
  searchStatus: string;
  lostHikerCount: number;
  telemetryMode: string;
  selectedAlgorithm: string;
};

export default function SwarmStatusPanel({
  elapsedSeconds,
  telemetryCount,
  validDroneCount,
  missionActive,
  searchStatus,
  lostHikerCount,
  telemetryMode,
  selectedAlgorithm
}: SwarmStatusPanelProps) {
  const algorithmLabel = selectedAlgorithm === "voronoi" ? "Voronoi" : "APF";
  return (
    <CollapsibleSection title="Swarm Status">
      <div className="kv-grid">
        <span>Time Elapsed</span>
        <strong>{formatElapsed(elapsedSeconds)}</strong>
        <span>Active Drones</span>
        <strong>{telemetryCount}</strong>
        <span>Valid Drones</span>
        <strong>{validDroneCount}</strong>
        <span>Search Status</span>
        <strong>{missionActive ? <SearchingLabel text="Searching" /> : statusLabel(searchStatus)}</strong>
        <span>Telemetry</span>
        <strong className={telemetryMode === "LIVE SITL" ? "success" : telemetryMode === "SIMULATED" ? "warning-text" : ""}>
          {telemetryMode}
        </strong>
        <span>Hikers Lost</span>
        <strong>{lostHikerCount}</strong>
        <span>Algorithm</span>
        <strong>{algorithmLabel}</strong>
      </div>
    </CollapsibleSection>
  );
}
