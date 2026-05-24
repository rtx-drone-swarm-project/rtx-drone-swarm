import type { Bounds, Target } from "../../types/mission";
import { estimateBoundsAreaKm2 } from "../../utils/geo";
import { formatElapsed, statusLabel } from "../../utils/format";
import CollapsibleSection from "../common/CollapsibleSection";
import SearchingLabel from "../common/SearchingLabel";

type OperatorStatusPanelProps = {
  elapsedSeconds: number;
  droneCount: number;
  missionComplete: boolean;
  missionStatus: string;
  placedHikerCount: number;
  progress: number;
  selectedBounds: Bounds | null;
  targets: Target[];
  telemetryMode: string;
};

function missionCue({
  missionComplete,
  missionStatus,
  selectedBounds
}: Pick<OperatorStatusPanelProps, "missionComplete" | "missionStatus" | "selectedBounds">) {
  if (missionComplete) {
    return {
      chipClass: "complete",
      icon: "OK",
      text: "Mission complete. Reset mission when ready for the next search."
    };
  }

  if (missionStatus === "searching") {
    return {
      chipClass: "info",
      icon: "SR",
      text: <SearchingLabel text="Search in progress. Monitor found hiker updates." />
    };
  }

  if (missionStatus === "search_complete") {
    return {
      chipClass: "info",
      icon: "SR",
      text: "All hikers found. Recall drones."
    };
  }

  if (missionStatus === "recalling") {
    return {
      chipClass: "info",
      icon: "RT",
      text: <SearchingLabel text="Recall in progress. Monitor return status." />
    };
  }

  if (missionStatus === "paused") {
    return {
      chipClass: "stopped",
      icon: "PA",
      text: "Mission paused. Reset mission when ready to re-plan."
    };
  }

  if (selectedBounds) {
    return {
      chipClass: "warning",
      icon: "GO",
      text: "Area selected. Start mission when ready."
    };
  }

  return {
    chipClass: "info",
    icon: "AR",
    text: "Select a search area to begin."
  };
}

function formatSearchArea(bounds: Bounds | null) {
  if (!bounds) return "Not selected";
  const area = estimateBoundsAreaKm2(bounds);
  if (area >= 10) return `${Math.round(area)} km2`;
  return `${area.toFixed(1)} km2`;
}

function hikerObjective(targets: Target[], placedHikerCount: number) {
  if (targets.length > 0) {
    const found = targets.filter((target) => target.status === "found").length;
    const remaining = Math.max(targets.length - found, 0);
    return `${found}/${targets.length} found, ${remaining} remaining`;
  }

  if (placedHikerCount > 0) {
    return `${placedHikerCount} planned`;
  }

  return "Random hikers on start";
}

export default function OperatorStatusPanel({
  elapsedSeconds,
  droneCount,
  missionComplete,
  missionStatus,
  placedHikerCount,
  progress,
  selectedBounds,
  targets,
  telemetryMode
}: OperatorStatusPanelProps) {
  const cue = missionCue({ missionComplete, missionStatus, selectedBounds });
  const progressLabel = `${Math.round(Math.max(0, Math.min(progress, 100)))}%`;

  return (
    <CollapsibleSection title="Operator Status">
      <div className="stack-list operator-status">
        <div className={`alert-chip ${cue.chipClass}`}>
          <span className="alert-icon operator-cue-icon">{cue.icon}</span>
          <div>
            <div className="alert-title">Next action</div>
            <div className="alert-sub">{cue.text}</div>
          </div>
        </div>

        <div className="kv-grid operator-status-grid">
          <span>Mission Phase</span>
          <strong>{statusLabel(missionStatus)}</strong>
          <span>Elapsed</span>
          <strong>{formatElapsed(elapsedSeconds)}</strong>
          <span>Progress</span>
          <strong>{progressLabel}</strong>
          <span>Hiker Objective</span>
          <strong>{hikerObjective(targets, placedHikerCount)}</strong>
          <span>Search Area</span>
          <strong>{formatSearchArea(selectedBounds)}</strong>
          <span>Drones Assigned</span>
          <strong>{droneCount}</strong>
          <span>Telemetry Source</span>
          <strong className={telemetryMode === "LIVE SITL" ? "success" : telemetryMode === "SIMULATED" ? "warning-text" : ""}>
            {telemetryMode}
          </strong>
        </div>
      </div>
    </CollapsibleSection>
  );
}
