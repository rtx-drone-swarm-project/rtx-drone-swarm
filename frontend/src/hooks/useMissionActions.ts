import { useMemo } from "react";
import { createMissionClient } from "../api/missionClient";
import type { AlgorithmOption, Bounds, FoundHiker, MissionDroneInput, MissionHikerInput, MissionState, PlacedHiker, Target, ValidDrone } from "../types/mission";
import type { MissionStatus } from "../types/ws";

type UseMissionActionsArgs = {
  apiBase: string;
  missionLocked: boolean;
  selectedBounds: Bounds | null;
  selectedAlgorithm: AlgorithmOption;
  placedHikers: PlacedHiker[];
  validDrones: ValidDrone[];
  validDroneCount: number;
  mission: MissionState;
  setMission: (value: MissionState) => void;
  setMissionStatus: (value: MissionStatus) => void;
  setProgress: (value: number) => void;
  setTargets: (value: Target[]) => void;
  setElapsedSeconds: (value: number) => void;
  setMissionLocked: (value: boolean) => void;
  setFoundHikers: (value: FoundHiker[]) => void;
  setSearchSummaryOpen: (value: boolean) => void;
  setCompletedTargets: (value: Target[]) => void;
  setSummaryMissionId: (value: string | number | null) => void;
  setHikerLabelById: (value: Record<string, number>) => void;
  setIsValidBounds: (value: boolean) => void;
  clearTemporaryRegionSelection: () => void;
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

function toMissionHikerInput(hiker: PlacedHiker): MissionHikerInput {
  const payload: MissionHikerInput = {
    id: hiker.id,
    lat: hiker.lat,
    lon: hiker.lon,
    found: false,
  };

  if (hiker.movement) payload.movement = hiker.movement;

  return payload;
}

function buildMissionDrones(
  validDrones: ValidDrone[],
  validDroneCount: number,
  bounds: Bounds
): MissionDroneInput[] {
  if (validDroneCount > 0) {
    return validDrones.map(toMissionDroneInput);
  }

  return Array.from({ length: 15 }).map((_, i) =>
    toMissionDroneInput({
      id: `mock-drone-${i}`,
      lat: bounds.min_lat + Math.random() * (bounds.max_lat - bounds.min_lat),
      lon: bounds.min_lon + Math.random() * (bounds.max_lon - bounds.min_lon),
      alt: 100,
      heading: Math.random() * 360,
    })
  );
}

export default function useMissionActions({
  apiBase,
  missionLocked,
  selectedBounds,
  selectedAlgorithm,
  placedHikers,
  validDrones,
  validDroneCount,
  mission,
  setMission,
  setMissionStatus,
  setProgress,
  setTargets,
  setElapsedSeconds,
  setMissionLocked,
  setFoundHikers,
  setSearchSummaryOpen,
  setCompletedTargets,
  setSummaryMissionId,
  setHikerLabelById,
  setIsValidBounds,
  clearTemporaryRegionSelection,
}: UseMissionActionsArgs) {
  const missionClient = useMemo(() => createMissionClient(apiBase), [apiBase]);

  const confirmSearchArea = async () => {
    if (!selectedBounds) {
      setIsValidBounds(false);
      return;
    }

    let missionRecord = mission;

    try {
      if (!missionRecord?.id) {
        missionRecord = await missionClient.createMission({
          name: `SAR-${new Date().toISOString()}`,
          bounds: selectedBounds,
        });
      }

      const confirmedMission = await missionClient.confirmSearchArea(missionRecord.id, {
        bounds: selectedBounds
      });
      clearTemporaryRegionSelection();
      setMission(confirmedMission);
    } catch (err) {
      console.warn(`Confirm search area failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  const startMission = async () => {
    if (missionLocked || !selectedBounds) {
      console.warn("Start failed: search area must be confirmed before starting the mission");
      return;
    }
    if (!mission?.id || mission.search_area_confirmed !== true || mission.probability_grid_confirmed !== true) {
      console.warn("Start failed: search area and probability map must both be confirmed before starting the mission");
      return;
    }

    setMissionStatus("searching");
    setElapsedSeconds(0);
    setMissionLocked(false);
    setFoundHikers([]);
    setSearchSummaryOpen(false);
    setCompletedTargets([]);
    setSummaryMissionId(null);
    setHikerLabelById({});

    const missionDrones: MissionDroneInput[] = buildMissionDrones(validDrones, validDroneCount, selectedBounds);
    const missionHikers: MissionHikerInput[] = placedHikers.map(toMissionHikerInput);
    try {
      let missionRecord = mission;
      if (!missionRecord?.id) {
        missionRecord = await missionClient.createMission({
          name: `SAR-${new Date().toISOString()}`,
          bounds: selectedBounds,
          drones: missionDrones,
          hikers: missionHikers,
          algorithm: selectedAlgorithm,
        });
        setMission(missionRecord);
      }

      const payload = {
        drones: missionDrones,
        hikers: missionHikers,
        algorithm: selectedAlgorithm,
      }
      const started = await missionClient.startMission(missionRecord.id, payload);
      setMission(started);
      setMissionStatus("searching");
      setProgress(started.progress ?? 0);
      if (Array.isArray(started.targets)) setTargets(started.targets);
    } catch (err) {
      setMissionStatus("idle");
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
      setMissionStatus("paused");
      setProgress(0);
    } catch (err) {
      console.warn(`Stop failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const resetMissionLock = async () => {
    const missionId = mission?.id;
    setMissionLocked(false);
    setMission(null);
    setMissionStatus("idle");
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

  return {
    confirmSearchArea,
    startMission,
    stopMission,
    resetMissionLock,
    recallDrones,
  };
}
