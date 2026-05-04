import { algorithmDisplayLabel } from "../../types/mission";
import { formatElapsed, statusLabel } from "../../utils/format";
import CollapsibleSection from "../common/CollapsibleSection";
import SearchingLabel from "../common/SearchingLabel";

type SwarmStatusPanelProps = {
  elapsedSeconds: number;
  telemetryCount: number;
  validDroneCount: number;
  missionActive: boolean;
  missionStatus: string;
  lostHikerCount: number;
  telemetryMode: string;
  selectedAlgorithm: string;
};

export default function SwarmStatusPanel({
  elapsedSeconds,
  telemetryCount,
  validDroneCount,
  missionActive,
  missionStatus,
  lostHikerCount,
  telemetryMode,
  selectedAlgorithm
}: SwarmStatusPanelProps) {
  const algorithmLabel = algorithmDisplayLabel(selectedAlgorithm);
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
        <strong>{statusLabel(missionStatus)}</strong>
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
