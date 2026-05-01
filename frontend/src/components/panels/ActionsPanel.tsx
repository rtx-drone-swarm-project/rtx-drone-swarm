import type { AlgorithmOption, Bounds, MissionRecord } from "../../types/mission";
import CollapsibleSection from "../common/CollapsibleSection";

const ALGORITHM_OPTIONS: { value: AlgorithmOption; label: string }[] = [
  { value: "voronoi", label: "Voronoi (Lloyd's)" },
  { value: "apf", label: "APF (Potential Fields)" }
];

type ActionsPanelProps = {
  selectedBounds: Bounds | null;
  missionActive: boolean;
  missionLocked: boolean;
  validDroneCount: number;
  mission: MissionRecord | null;
  selectedAlgorithm: AlgorithmOption;
  onAlgorithmChange: (algorithm: AlgorithmOption) => void;
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
  selectedAlgorithm,
  onAlgorithmChange,
  onStartMission,
  onStopMission,
  onResetMission
}: ActionsPanelProps) {
  const selectorDisabled = missionActive || missionLocked;

  return (
    <CollapsibleSection title="Actions">
      <div className="algorithm-selector">
        <label className="algorithm-label" htmlFor="algorithm-select">
          Algorithm
        </label>
        <select
          id="algorithm-select"
          className="algorithm-select"
          value={selectedAlgorithm}
          onChange={(e) => onAlgorithmChange(e.target.value as AlgorithmOption)}
          disabled={selectorDisabled}
        >
          {ALGORITHM_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      <button
        className="action-btn start mission-start"
        onClick={onStartMission}
        disabled={!selectedBounds || missionActive || missionLocked}
      >
        {missionLocked ? "Mission Complete" : "Start Mission"}
      </button>

      {!selectedBounds && <div className="hint-text">Enter coordinates above and press "Set Search Area", or Shift-drag on the map to draw the search area.</div>}

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
