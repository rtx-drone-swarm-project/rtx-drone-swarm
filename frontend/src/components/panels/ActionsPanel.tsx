import type { Bounds, MissionRecord } from "../../types/mission";
import CollapsibleSection from "../common/CollapsibleSection";

type ActionsPanelProps = {
  selectedBounds: Bounds | null;
  missionActive: boolean;
  missionLocked: boolean;
  validDroneCount: number;
  mission: MissionRecord | null;
  onStartMission: () => void;
  onStopMission: () => void;
  onResetMission: () => void;
};

export default function ActionsPanel({
  selectedBounds,
  missionActive,
  missionLocked,
  validDroneCount,
  mission,
  onStartMission,
  onStopMission,
  onResetMission
}: ActionsPanelProps) {
  return (
    <CollapsibleSection title="Actions">
      <button
        className="action-btn start"
        onClick={onStartMission}
        disabled={!selectedBounds || missionActive || missionLocked}
      >
        {missionLocked ? "Mission Complete" : "Start Mission"}
      </button>

      {!selectedBounds && <div className="hint-text">Enter coordinates above and press "Set Search Area", or drag on the map to draw the search area.</div>}

      {missionLocked && (
        <div className="hint-text success-text">Mission locked after completion. Reset to run another.</div>
      )}

      {validDroneCount < 15 && (
        <div className="hint-text warning-text">Warning: only {validDroneCount} valid drones (15 recommended).</div>
      )}

      <button className="action-btn stop" onClick={onStopMission} disabled={!mission?.id || !missionActive}>
        Stop Mission
      </button>

      <button className="action-btn reset" onClick={onResetMission} disabled={missionActive}>
        Reset Mission
      </button>
    </CollapsibleSection>
  );
}
