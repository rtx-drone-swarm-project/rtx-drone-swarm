import { formatElapsed, statusLabel } from "../../utils/format";
import CollapsibleSection from "../common/CollapsibleSection";
import SearchingLabel from "../common/SearchingLabel";

type SwarmStatusPanelProps = {
  elapsedSeconds: number;
  telemetryCount: number;
  validDroneCount: number;
  missionActive: boolean;
  searchStatus: string;
  averageBattery: string;
  lostHikerCount: number;
};

export default function SwarmStatusPanel({
  elapsedSeconds,
  telemetryCount,
  validDroneCount,
  missionActive,
  searchStatus,
  averageBattery,
  lostHikerCount
}: SwarmStatusPanelProps) {
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
        <span>Battery</span>
        <strong>{averageBattery}</strong>
        <span>Latency</span>
        <strong className="success">live</strong>
        <span>Hikers Lost</span>
        <strong>{lostHikerCount}</strong>
      </div>
    </CollapsibleSection>
  );
}
