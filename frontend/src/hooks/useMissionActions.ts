import { useMemo } from "react";
import { createMissionClient } from "../api/missionClient";
import type { AlgorithmOption, Bounds, FoundHiker, MissionDroneInput, MissionState, Target, ValidDrone } from "../types/mission";
import { normalizeMissionStatus } from "../utils/format";

type UseMissionActionsArgs = {
  apiBase: string;
  missionLocked: boolean;
  selectedBounds: Bounds | null;
  selectedAlgorithm: AlgorithmOption;
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
  setSearchSummaryOpen: (value: boolean) => void;
  setCompletedTargets: (value: Target[]) => void;
  setSummaryMissionId: (value: string | number | null) => void;
  setHikerLabelById: (value: Record<string, number>) => void;
};

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function hasText(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function toMissionDroneInput(drone: ValidDrone): MissionDroneInput {
  const payload: MissionDroneInput = {
    id: drone.id,
    lat: drone.lat,
    lon: drone.lon
  };

  if (isFiniteNumber(drone.sysid)) payload.sysid = drone.sysid;
  if (isFiniteNumber(drone.alt)) payload.alt = drone.alt;
  if (isFiniteNumber(drone.heading)) payload.heading = drone.heading;
  if (isFiniteNumber(drone.groundspeed)) payload.groundspeed = drone.groundspeed;
  if (isFiniteNumber(drone.target_lat)) payload.target_lat = drone.target_lat;
  if (isFiniteNumber(drone.target_lon)) payload.target_lon = drone.target_lon;
  if (hasText(drone.role)) payload.role = drone.role;

  return payload;
}

export default function useMissionActions({
  apiBase,
  missionLocked,
  selectedBounds,
  selectedAlgorithm,
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
  setSearchSummaryOpen,
  setCompletedTargets,
  setSummaryMissionId,
  setHikerLabelById
}: UseMissionActionsArgs) {
  const missionClient = useMemo(() => createMissionClient(apiBase), [apiBase]);

  const startMission = async () => {
    if (missionLocked) {
      return;
    }

    if (!selectedBounds) {
      return;
    }

    let missionDrones: MissionDroneInput[] = validDrones.map(toMissionDroneInput);

    if (validDroneCount === 0) {
      missionDrones = Array.from({ length: 15 }).map((_, i) =>
        toMissionDroneInput({
          id: `mock-drone-${i}`,
          lat: selectedBounds.min_lat + Math.random() * (selectedBounds.max_lat - selectedBounds.min_lat),
          lon: selectedBounds.min_lon + Math.random() * (selectedBounds.max_lon - selectedBounds.min_lon),
          alt: 100,
          heading: Math.random() * 360
        })
      );
    }

    setSearchStatus("running");
    setElapsedSeconds(0);
    setMissionLocked(false);
    setFoundHikers([]);
    setSearchSummaryOpen(false);
    setCompletedTargets([]);
    setSummaryMissionId(null);
    setHikerLabelById({});

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

      const started = await missionClient.startMission(
        created.id,
        selectedAlgorithm !== "default" ? selectedAlgorithm : undefined
      );
      setMission(started);
      setSearchStatus(normalizeMissionStatus(started.status ?? "running"));
      setProgress(started.progress ?? 0);
      if (Array.isArray(started.targets)) setTargets(started.targets);
    } catch (err) {
      setSearchStatus("idle");
      console.warn(`Start failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const stopMission = async () => {
    if (!mission?.id) {
      return;
    }

    try {
      const stopped = await missionClient.stopMission(mission.id);
      setMission(stopped);
      setSearchStatus(normalizeMissionStatus(stopped.status ?? "idle"));
      setProgress(0);
    } catch (err) {
      console.warn(`Stop failed: ${err instanceof Error ? err.message : String(err)}`);
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
    setSearchSummaryOpen(false);
    setCompletedTargets([]);
    setSummaryMissionId(null);
    setHikerLabelById({});
    if (missionId) {
      try {
        await missionClient.deleteMission(missionId);
      } catch {
        // Mission may already be gone (404); ignore silently
      }
    }
  };

  const recallDrones = async () => {
    if (!mission?.id) return;
    await missionClient.recallMission(mission.id);
  };

  const resetDrones = async () => {
    if (!mission?.id) return;
    await missionClient.resetMission(mission.id);
  };

  return {
    startMission,
    stopMission,
    resetMissionLock,
    recallDrones,
    resetDrones,
  };
}
