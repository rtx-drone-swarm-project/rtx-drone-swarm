import { useMemo } from "react";
import { createMissionClient } from "../api/missionClient";
import type { Bounds, FoundHiker, MissionState, Target, ValidDrone } from "../types/mission";
import { normalizeMissionStatus } from "../utils/format";

type UseMissionActionsArgs = {
  apiBase: string;
  missionLocked: boolean;
  selectedBounds: Bounds | null;
  validDrones: ValidDrone[];
  validDroneCount: number;
  mission: MissionState;
  setMission: (value: MissionState) => void;
  setSearchStatus: (value: string) => void;
  setProgress: (value: number) => void;
  setTargets: (value: Target[]) => void;
  setElapsedSeconds: (value: number) => void;
  setMissionLocked: (value: boolean) => void;
  setFoundHikers: (value: FoundHiker[]) => void;
  setHikerSummaryOpen: (value: boolean) => void;
  setCompletedTargets: (value: Target[]) => void;
  setSummaryMissionId: (value: string | number | null) => void;
  pushAlert: (message: string) => void;
};

export default function useMissionActions({
  apiBase,
  missionLocked,
  selectedBounds,
  validDrones,
  validDroneCount,
  mission,
  setMission,
  setSearchStatus,
  setProgress,
  setTargets,
  setElapsedSeconds,
  setMissionLocked,
  setFoundHikers,
  setHikerSummaryOpen,
  setCompletedTargets,
  setSummaryMissionId,
  pushAlert
}: UseMissionActionsArgs) {
  const missionClient = useMemo(() => createMissionClient(apiBase), [apiBase]);

  const startMission = async () => {
    if (missionLocked) {
      pushAlert("Mission is locked after completion. Reset mission to start another.");
      return;
    }

    if (!selectedBounds) {
      pushAlert("Click the map first to place a marker and auto-select 100km^2.");
      return;
    }

    let missionDrones = validDrones.map((drone) => ({ ...drone }));

    if (validDroneCount === 0) {
      pushAlert("No live drones from telemetry. Generating mock drones...");
      missionDrones = Array.from({ length: 15 }).map((_, i) => ({
        id: `mock-drone-${i}`,
        lat: selectedBounds.min_lat + Math.random() * (selectedBounds.max_lat - selectedBounds.min_lat),
        lon: selectedBounds.min_lon + Math.random() * (selectedBounds.max_lon - selectedBounds.min_lon),
        alt: 100,
        heading: Math.random() * 360,
      }));
    }

    pushAlert("Starting mission...");
    setSearchStatus("running");
    setElapsedSeconds(0);
    setMissionLocked(false);
    setFoundHikers([]);
    setHikerSummaryOpen(false);
    setCompletedTargets([]);
    setSummaryMissionId(null);

    try {
      const created = await missionClient.createMission({
        name: `SAR-${new Date().toISOString()}`,
        bounds: selectedBounds,
        drones: missionDrones,
        hikers: [
          {
            id: "hiker-1",
            lat: selectedBounds.min_lat + Math.random() * (selectedBounds.max_lat - selectedBounds.min_lat),
            lon: selectedBounds.min_lon + Math.random() * (selectedBounds.max_lon - selectedBounds.min_lon),
            found: false
          }
        ]
      });

      setMission(created);

      const started = await missionClient.startMission(created.id);
      setMission(started);
      setSearchStatus(normalizeMissionStatus(started.status ?? "running"));
      setProgress(started.progress ?? 0);
      if (Array.isArray(started.targets)) setTargets(started.targets);
      pushAlert(`Mission started (${started.id}).`);
    } catch (err) {
      setSearchStatus("idle");
      pushAlert(`Start failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const stopMission = async () => {
    if (!mission?.id) {
      pushAlert("No active mission to stop.");
      return;
    }

    try {
      const stopped = await missionClient.stopMission(mission.id);
      setMission(stopped);
      setSearchStatus(normalizeMissionStatus(stopped.status ?? "idle"));
      setProgress(0);
      pushAlert(`Mission stopped (${stopped.id}).`);
    } catch (err) {
      pushAlert(`Stop failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const resetMissionLock = async () => {
    const missionId = mission?.id;
    setMissionLocked(false);
    setMission(null);
    setSearchStatus("idle");
    setProgress(0);
    setTargets([]);
    setFoundHikers([]);
    setElapsedSeconds(0);
    setHikerSummaryOpen(false);
    setCompletedTargets([]);
    setSummaryMissionId(null);
    if (missionId) {
      try {
        await missionClient.deleteMission(missionId);
      } catch {
        // Mission may already be gone (404); ignore silently
      }
    }
    pushAlert("Mission reset. Ready for a new mission.");
  };

  return {
    startMission,
    stopMission,
    resetMissionLock
  };
}
