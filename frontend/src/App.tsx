import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createMissionClient } from "./api/missionClient";
import { getApiBase, getApiPort } from "./api/runtime";
import TopBar from "./components/layout/TopBar";
import MapPanel from "./components/map/MapPanel";
import DroneModal from "./components/modals/DroneModal";
import HikerModal from "./components/modals/HikerModal";
import SearchSummaryModal from "./components/modals/SearchSummaryModal";
import ActionsPanel from "./components/panels/ActionsPanel";
import FoundHikersPanel from "./components/panels/FoundHikersPanel";
import HikerSetupPanel from "./components/panels/HikerSetupPanel";
import LegendPanel from "./components/panels/LegendPanel";
import NavigationPanel from "./components/panels/NavigationPanel";
import OperatorStatusPanel from "./components/panels/OperatorStatusPanel";
import useMissionActions from "./hooks/useMissionActions";
import useMissionSocket from "./hooks/useMissionSocket";
import { DEFAULT_ALGORITHM_OPTIONS } from "./types/mission";
import type {
  AlgorithmOption,
  AlgorithmMetadata,
  Bounds,
  FoundHiker,
  HikerMovement,
  MissionMetrics,
  MissionState,
  PlacedHiker,
  SelectedDrone,
  SetupStage,
  Target,
  TelemetryDrone,
  ValidDrone
} from "./types/mission";
import type {
  MissionProgressMessage,
  MissionStatus,
  MissionStatusMessage,
  PmvHeatmapMessage,
  TargetFoundMessage,
  TelemetryMessage
} from "./types/ws";
import { useProbabilityMapEditor } from "./hooks/useProbabilityMapEditor";
import { useSearchAreaSetup } from "./hooks/useSearchAreaSetup";

const DEFAULT_CENTER: [number, number] = [33.5, -117.2];
const DEFAULT_ZOOM = 13;

function clampPointToBounds(lat: number, lon: number, bounds: Bounds): [number, number] {
  return [
    Math.min(bounds.max_lat, Math.max(bounds.min_lat, lat)),
    Math.min(bounds.max_lon, Math.max(bounds.min_lon, lon))
  ];
}

export default function App() {
  const apiPort = getApiPort();
  const apiBase = useMemo(() => getApiBase(apiPort), [apiPort]);
  const apiClient = useMemo(() => createMissionClient(apiBase), [apiBase]);

  const [telemetry, setTelemetry] = useState<TelemetryDrone[]>([]);
  const [mission, setMission] = useState<MissionState>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [missionStatus, setMissionStatus] = useState<MissionStatus>("idle");
  const [progress, setProgress] = useState(0);
  const [targets, setTargets] = useState<Target[]>([]);
  const [foundHikers, setFoundHikers] = useState<FoundHiker[]>([]);
  const [missionLocked, setMissionLocked] = useState(false);
  const [mapCenter, setMapCenter] = useState<[number, number] | null>(DEFAULT_CENTER);
  const [mapAutocentered, setMapAutocentered] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [selectedDrone, setSelectedDrone] = useState<SelectedDrone>(null);
  const [searchSummaryOpen, setSearchSummaryOpen] = useState(false);
  const [completedTargets, setCompletedTargets] = useState<Target[]>([]);
  const [summaryMissionId, setSummaryMissionId] = useState<string | number | null>(null);
  const [selectedAlgorithm, setSelectedAlgorithm] = useState<AlgorithmOption>("voronoi");
  const [algorithmOptions, setAlgorithmOptions] = useState<AlgorithmMetadata[]>(DEFAULT_ALGORITHM_OPTIONS);
  const [completionElapsedSeconds, setCompletionElapsedSeconds] = useState<number>(0);
  const [completedMetrics, setCompletedMetrics] = useState<MissionMetrics | null>(null);
  const [pmvHeatmap, setPmvHeatmap] = useState<PmvHeatmapMessage | null>(null);
  const [placedHikers, setPlacedHikers] = useState<PlacedHiker[]>([]);
  const [selectedHikerId, setSelectedHikerId] = useState<string | null>(null);
  const [isPlacingHiker, setIsPlacingHiker] = useState(false);
  const [setupStage, setSetupStage] = useState<SetupStage>("search_area");
  const [showLabelledRegions, setShowLabelledRegions] = useState(false);
  const [showProbabilityHeatmap, setShowProbabilityHeatmap] = useState(false);

  // Ref so onMissionStatus can read current elapsed without it being a dep,
  // which would recreate the callback every second and reconnect the WebSocket.
  const elapsedSecondsRef = useRef(elapsedSeconds);
  const runningMissionIdRef = useRef<string | null>(null);
  const completedMetricsMissionIdRef = useRef<string | null>(null);
  const nextHikerNumberRef = useRef(1);
  useEffect(() => {
    elapsedSecondsRef.current = elapsedSeconds;
  }, [elapsedSeconds]);

  // Drone trails: last N positions per drone_id, updated from telemetry.
  const [droneTrails, setDroneTrails] = useState<Record<string, [number, number][]>>({});
  const TRAIL_MAX_POINTS = 120;
  const [hikerLabelById, setHikerLabelById] = useState<Record<string, number>>({});

  const {
    temporaryRegionBounds,
    temporaryRegionCells,
    temporaryRegionLabel,
    setTemporaryRegionLabel,
    clearTemporaryRegionSelection,
    onSelectTemporaryRegion,
    onApplyTemporaryRegion,
    onConfirmLabelledRegions,
    onReopenProbabilityGrid,
    onResetProbabilityGrid,
  } = useProbabilityMapEditor({
    apiClient,
    mission,
    setMission,
    probabilityRegionEditingEnabled: setupStage === "label_regions",
  });

  const {
    selectedBounds,
    topLeftLat,
    topLeftLon,
    bottomRightLat,
    bottomRightLon,
    isValidBounds,
    isPointInsideBounds,
    setIsValidBounds,
    onTopLeftLatChange,
    onTopLeftLonChange,
    onBottomRightLatChange,
    onBottomRightLonChange,
    onSelectArea,
    onSetSearchArea,
  } = useSearchAreaSetup({
    clearTemporaryRegionSelection,
    setMapCenter,
    setPlacedHikers,
    setIsPlacingHiker,
  });

  const telemetryMode = useMemo(() => {
    const sources = telemetry
      .map((drone) => drone.telemetry_source)
      .filter((value): value is string => typeof value === "string" && value.length > 0);
    if (!sources.length) return wsConnected ? "NO DATA" : "DISCONNECTED";
    if (sources.some((source) => source === "sitl")) return "LIVE SITL";
    if (sources.every((source) => source === "simulated")) return "SIMULATED";
    return "MIXED";
  }, [telemetry, wsConnected]);

  const validDrones = useMemo<ValidDrone[]>(
    () =>
      telemetry
        .map((drone) => {
          const latNum = Number(drone.lat);
          const lonNum = Number(drone.lon);
          if (!Number.isFinite(latNum) || !Number.isFinite(lonNum)) return null;

          const normalizedDrone: ValidDrone = {
            id: drone.id ?? "unknown",
            sysid: typeof drone.sysid === "number" ? drone.sysid : null,
            lat: latNum,
            lon: lonNum,
            telemetry_source: typeof drone.telemetry_source === "string" ? drone.telemetry_source : null,
            mode: typeof drone.mode === "string" ? drone.mode : null,
            armed: typeof drone.armed === "boolean" ? drone.armed : null,
            status: typeof drone.status === "string" ? drone.status : null,
            role: typeof drone.role === "string" ? drone.role : null
          };

          const altNum = Number(drone.alt);
          const headingNum = Number(drone.heading);
          const groundspeedNum = Number(drone.groundspeed);
          const targetLatNum = Number(drone.target_lat);
          const targetLonNum = Number(drone.target_lon);
          if (Number.isFinite(altNum)) normalizedDrone.alt = altNum;
          if (Number.isFinite(headingNum)) normalizedDrone.heading = headingNum;
          if (Number.isFinite(groundspeedNum)) normalizedDrone.groundspeed = groundspeedNum;
          if (Number.isFinite(targetLatNum)) normalizedDrone.target_lat = targetLatNum;
          if (Number.isFinite(targetLonNum)) normalizedDrone.target_lon = targetLonNum;

          if (
            Array.isArray(drone.sweep_centroid) &&
            Number.isFinite(Number(drone.sweep_centroid[0])) &&
            Number.isFinite(Number(drone.sweep_centroid[1]))
          ) {
            normalizedDrone.sweep_centroid = [
              Number(drone.sweep_centroid[0]),
              Number(drone.sweep_centroid[1])
            ];
          }
          if (typeof drone.sweep_phase === "string") {
            normalizedDrone.sweep_phase = drone.sweep_phase;
          }

          return normalizedDrone;
        })
        .filter((drone): drone is ValidDrone => drone !== null),
    [telemetry]
  );

  const validDroneCount = validDrones.length;

  const {
    confirmSearchArea,
    startMission,
    stopMission,
    resetMissionLock,
    recallDrones,
  } = useMissionActions({
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
    setCompletedMetrics,
    setSummaryMissionId,
    setHikerLabelById,
    setIsValidBounds,
    clearTemporaryRegionSelection,
  })

  useEffect(() => {
    let cancelled = false;
    apiClient.listAlgorithms()
      .then((payload) => {
        if (cancelled || !Array.isArray(payload.algorithms) || payload.algorithms.length === 0) return;
        setAlgorithmOptions(payload.algorithms);
        setSelectedAlgorithm((current) =>
          payload.algorithms.some((option) => option.key === current) ? current : payload.algorithms[0].key
        );
      })
      .catch(() => {
        // Keep built-in fallback options if the backend is not reachable yet.
      });
    return () => {
      cancelled = true;
    };
  }, [apiClient]);

  const getHikerLabel = useCallback(
    (targetId: string | number) => {
      const normalizedId = String(targetId);
      const sequenceNumber = hikerLabelById[normalizedId];
      return `Hiker ${sequenceNumber ?? normalizedId}`;
    },
    [hikerLabelById]
  );

  const assignHikerLabels = useCallback((targetIds: Array<string | number>) => {
    if (!targetIds.length) return;

    setHikerLabelById((prev) => {
      let nextIndex = Object.keys(prev).length + 1;
      let changed = false;
      const next = { ...prev };

      for (const targetId of targetIds) {
        const normalizedId = String(targetId);
        if (next[normalizedId] != null) continue;
        next[normalizedId] = nextIndex;
        nextIndex += 1;
        changed = true;
      }

      return changed ? next : prev;
    });
  }, []);

  const foundHikersSorted = useMemo(
    () =>
      [...foundHikers].sort((a, b) => {
        const left = hikerLabelById[String(a.id)] ?? Number.MAX_SAFE_INTEGER;
        const right = hikerLabelById[String(b.id)] ?? Number.MAX_SAFE_INTEGER;
        return left - right;
      }),
    [foundHikers, hikerLabelById]
  );

  const completedTargetsSorted = useMemo(
    () =>
      [...completedTargets].sort((a, b) => {
        const left = hikerLabelById[String(a.id)] ?? Number.MAX_SAFE_INTEGER;
        const right = hikerLabelById[String(b.id)] ?? Number.MAX_SAFE_INTEGER;
        return left - right;
      }),
    [completedTargets, hikerLabelById]
  );

  const getPlacedHikerLabel = useCallback(
    (_hiker: PlacedHiker, index: number) => `Hiker ${index + 1}`,
    []
  );

  const selectedPlacedHiker = useMemo(
    () => placedHikers.find((hiker) => hiker.id === selectedHikerId) ?? null,
    [placedHikers, selectedHikerId]
  );

  const selectedPlacedHikerLabel = useMemo(() => {
    if (!selectedPlacedHiker) return "";
    const index = placedHikers.findIndex((hiker) => hiker.id === selectedPlacedHiker.id);
    return getPlacedHikerLabel(selectedPlacedHiker, index >= 0 ? index : 0);
  }, [getPlacedHikerLabel, placedHikers, selectedPlacedHiker]);

  useEffect(() => {
    if (missionStatus !== "searching") return;
    const interval = window.setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [missionStatus]);

  const onTelemetry = useCallback((message: TelemetryMessage) => {
    const drones = Array.isArray(message.drones) ? message.drones : [];
    setTelemetry(drones);
    setDroneTrails((prev) => {
      const next = { ...prev };
      for (const d of drones) {
        const lat = Number(d.lat);
        const lon = Number(d.lon);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue;
        const key = String(d.id);
        const history = next[key] ?? [];
        const last = history[history.length - 1];
        if (!last || last[0] !== lat || last[1] !== lon) {
          const updated = [...history, [lat, lon] as [number, number]];
          next[key] = updated.slice(-TRAIL_MAX_POINTS);
        }
      }
      return next;
    });
    setMapAutocentered((prev) => {
      if (prev) return prev;
      const lats = drones.map((d) => Number(d.lat)).filter(Number.isFinite);
      const lons = drones.map((d) => Number(d.lon)).filter(Number.isFinite);
      if (!lats.length) return prev;
      const avgLat = lats.reduce((a, b) => a + b, 0) / lats.length;
      const avgLon = lons.reduce((a, b) => a + b, 0) / lons.length;
      setMapCenter([avgLat, avgLon]);
      return true;
    });
  }, []);

  const onMissionStatus = useCallback(
    (message: MissionStatusMessage) => {
      setMissionStatus(message.status);
      if (typeof message.progress === "number") setProgress(message.status === "search_complete" ? 100 : message.progress);
      if (Array.isArray(message.targets)) {
        assignHikerLabels(message.targets.map((target) => target.id));
        setTargets(message.targets);
      }

      if (message.status === "mission_complete") {
        setCompletionElapsedSeconds(elapsedSecondsRef.current);
        setElapsedSeconds(0);
        setMissionLocked(true);
      }
      if (message.status === "searching") {
        const runningMissionId = message.mission_id != null ? String(message.mission_id) : "__unknown_running_mission__";
        if (runningMissionIdRef.current !== runningMissionId) {
          runningMissionIdRef.current = runningMissionId;
          setDroneTrails({});
        }
        setCompletedMetrics(null);
        completedMetricsMissionIdRef.current = null;
      } else if (message.status === "search_complete") {
        runningMissionIdRef.current = null;
        setPmvHeatmap(null);
        const missionId = message.mission_id;
        const allTargetsFound = Array.isArray(message.targets) && message.targets.length > 0 && message.targets.every((target) => target.status === "found");
        if (missionId != null && allTargetsFound) {
          const metricsMissionId = String(missionId);
          completedMetricsMissionIdRef.current = metricsMissionId;
          apiClient.getMissionMetrics(missionId)
            .then((metrics) => {
              if (completedMetricsMissionIdRef.current === metricsMissionId) {
                setCompletedMetrics(metrics);
              }
            })
            .catch(() => undefined);
        }
      } else {
        runningMissionIdRef.current = null;
        setPmvHeatmap(null);
      }
    },
    [apiClient, assignHikerLabels]
  );

  const onMissionProgress = useCallback((message: MissionProgressMessage) => {
    if (typeof message.progress === "number") setProgress(message.progress);
  }, []);

  const onTargetFound = useCallback(
    (message: TargetFoundMessage) => {
      const rawId = message.target_id ?? `target-${Date.now()}`;
      const foundId = typeof rawId === "number" || typeof rawId === "string" ? rawId : String(rawId);
      const foundLat = Number(message.lat);
      const foundLon = Number(message.lon);
      const foundAt = typeof message.found_at === "number" ? message.found_at : undefined;
      const canStore = Number.isFinite(foundLat) && Number.isFinite(foundLon);
      assignHikerLabels([foundId]);

      if (canStore) {
        setFoundHikers((prev) => {
          if (prev.some((hiker) => String(hiker.id) === String(foundId))) return prev;
          return [...prev, { id: foundId, lat: foundLat, lon: foundLon, foundAt }];
        });
      }

    },
    [assignHikerLabels]
  );

  const onPmvHeatmap = useCallback((message: PmvHeatmapMessage) => {
    if (message.algorithm !== "pmv") return;
    if (!Array.isArray(message.values) || message.values.length !== message.rows * message.cols) return;
    setPmvHeatmap(message);
  }, []);

  useMissionSocket({
    apiPort,
    onConnectedChange: setWsConnected,
    onTelemetry,
    onMissionStatus,
    onMissionProgress,
    onTargetFound,
    onPmvHeatmap
  });

  const missionActive = missionStatus !== "idle" && missionStatus !== "mission_complete";
  const missionComplete = missionStatus === "mission_complete";
  const hikerPlacementEditable = selectedBounds != null && !missionActive && !missionLocked;

  useEffect(() => {
    if (!hikerPlacementEditable) {
      setIsPlacingHiker(false);
    }
  }, [hikerPlacementEditable]);

  useEffect(() => {
    if (missionActive && setupStage !== "active_mission") {
      setSetupStage("active_mission");
      setShowProbabilityHeatmap(false);
      setShowLabelledRegions(false);
      clearTemporaryRegionSelection();
    }
  }, [clearTemporaryRegionSelection, missionActive, setupStage]);

  useEffect(() => {
    if (selectedAlgorithm !== "pmv" || !missionActive) {
      setPmvHeatmap(null);
    }
  }, [missionActive, selectedAlgorithm]);

  // Mission action handlers (single, canonical call above)
  useEffect(() => {
    if (!mission || !targets.length) return;
    const allFound = targets.every((t) => t.status === "found");
    if (!allFound) return;
    if (summaryMissionId === mission.id) return;

    setCompletionElapsedSeconds(elapsedSeconds);
    setCompletedTargets(targets);
    setSummaryMissionId(mission.id);
    setSearchSummaryOpen(true);
  }, [mission, summaryMissionId, targets]);

  useEffect(() => {
    if (!targets.length) return;
    assignHikerLabels(targets.map((target) => target.id));
    setFoundHikers((prev) => {
      const existing = new Set(prev.map((hiker) => String(hiker.id)));
      const discovered = targets
        .filter((target) => target.status === "found" && !existing.has(String(target.id)))
        .map((target) => ({ id: target.id, lat: target.lat, lon: target.lon }));
      return discovered.length ? [...prev, ...discovered] : prev;
    });
  }, [assignHikerLabels, targets]);

  const onAlgorithmChange = useCallback((algorithm: AlgorithmOption) => {
    setSelectedAlgorithm(algorithm);
    runningMissionIdRef.current = null;
    setDroneTrails({});
    setPmvHeatmap(null);
  }, []);

  const configureProbabilityMap = useCallback(async () => {
    if (!selectedBounds) {
      setIsValidBounds(false);
      return;
    }

    const confirmedMission = await confirmSearchArea();
    if (!confirmedMission) return;

    clearTemporaryRegionSelection();
    setSetupStage("label_regions");
    setShowLabelledRegions(true);
    setShowProbabilityHeatmap(false);
  }, [clearTemporaryRegionSelection, confirmSearchArea, selectedBounds, setIsValidBounds]);

  const backFromLabelRegions = useCallback(async () => {
    if (mission?.id) {
      await onResetProbabilityGrid();
    } else {
      setMission((current) =>
        current
          ? {
              ...current,
              probability_grid_confirmed: false,
            }
          : current
      );
    }

    clearTemporaryRegionSelection();
    setSetupStage("search_area");
    setShowLabelledRegions(false);
    setShowProbabilityHeatmap(false);
  }, [clearTemporaryRegionSelection, mission?.id, onResetProbabilityGrid, setMission]);

  const handleConfirmLabelledRegions = useCallback(async () => {
    const confirmedMission = await onConfirmLabelledRegions();
    if (!confirmedMission) return;

    clearTemporaryRegionSelection();
    setSetupStage("review_probability_map");
    setShowProbabilityHeatmap(true);
    setShowLabelledRegions(false);
  }, [clearTemporaryRegionSelection, onConfirmLabelledRegions]);

  const backFromReview = useCallback(async () => {
    if (mission?.id) {
      await onReopenProbabilityGrid();
    } else {
      setMission((current) =>
        current
          ? {
              ...current,
              probability_grid_confirmed: false,
            }
          : current
      );
    }

    clearTemporaryRegionSelection();
    setSetupStage("label_regions");
    setShowProbabilityHeatmap(false);
    setShowLabelledRegions(true);
  }, [clearTemporaryRegionSelection, mission?.id, onReopenProbabilityGrid, setMission]);

  const handleStartMission = useCallback(async () => {
    if (setupStage === "label_regions") {
      return;
    }

    if (setupStage === "review_probability_map" && mission?.probability_grid_confirmed !== true) {
      return;
    }

    const startedMission = await startMission();
    if (!startedMission) return;

    clearTemporaryRegionSelection();
    setSetupStage("active_mission");
    setShowProbabilityHeatmap(false);
    setShowLabelledRegions(false);
  }, [clearTemporaryRegionSelection, mission?.probability_grid_confirmed, setupStage, startMission]);

  const probabilityMapAvailable = mission?.probability_grid_confirmed === true;

  const probabilityMapConfigured = setupStage !== "search_area" || mission?.probability_grid_confirmed === true;

  const canStartMission = useMemo(() => {
    if (!selectedBounds || missionActive || missionLocked) return false;
    if (setupStage === "label_regions") return false;
    if (setupStage === "review_probability_map") {
      return mission?.probability_grid_confirmed === true;
    }
    return true;
  }, [mission?.probability_grid_confirmed, missionActive, missionLocked, selectedBounds, setupStage]);

  const startMissionHelperText = useMemo(() => {
    if (setupStage === "label_regions") {
      return "Finish or go back from probability-map setup before starting.";
    }
    if (selectedBounds && !missionActive && !missionLocked && !probabilityMapConfigured) {
      return "Optional: configure a probability map before starting if you want weighted search behavior.";
    }
    return null;
  }, [missionActive, missionLocked, probabilityMapConfigured, selectedBounds, setupStage]);

  const searchAreaEditingDisabled = setupStage === "active_mission";

  const onResetMission = useCallback(() => {
    runningMissionIdRef.current = null;
    completedMetricsMissionIdRef.current = null;
    nextHikerNumberRef.current = 1;
    setDroneTrails({});
    setPmvHeatmap(null);
    setPlacedHikers([]);
    setSelectedHikerId(null);
    setIsPlacingHiker(false);
    // clear any completed metrics and elapsed counters
    setCompletedMetrics(null);
    setCompletionElapsedSeconds(0);
    // reset probability-map UI state
    clearTemporaryRegionSelection();
    setSetupStage("search_area");
    setShowLabelledRegions(false);
    setShowProbabilityHeatmap(false);
    resetMissionLock();
  }, [clearTemporaryRegionSelection, resetMissionLock]);

  const onAddHiker = useCallback(() => {
    if (!selectedBounds || !hikerPlacementEditable) return;
    setSelectedHikerId(null);
    setIsPlacingHiker((current) => !current);
  }, [hikerPlacementEditable, selectedBounds]);

  const onPlaceHiker = useCallback(
    (nextLat: number, nextLon: number) => {
      if (!selectedBounds || !hikerPlacementEditable || !isPlacingHiker) return;
      if (!isPointInsideBounds(nextLat, nextLon, selectedBounds)) return;
      const newHiker: PlacedHiker = {
        id: `hiker-${nextHikerNumberRef.current}`,
        lat: nextLat,
        lon: nextLon,
        movement: "stationary"
      };
      nextHikerNumberRef.current += 1;
      setPlacedHikers((prev) => [...prev, newHiker]);
    },
    [hikerPlacementEditable, isPlacingHiker, selectedBounds]
  );

  const onMoveHiker = useCallback(
    (hikerId: string, nextLat: number, nextLon: number) => {
      if (!selectedBounds || !hikerPlacementEditable) return;
      const [lat, lon] = clampPointToBounds(nextLat, nextLon, selectedBounds);
      setPlacedHikers((prev) => prev.map((hiker) => (hiker.id === hikerId ? { ...hiker, lat, lon } : hiker)));
    },
    [hikerPlacementEditable, selectedBounds]
  );

  const onHikerMovementChange = useCallback(
    (movement: HikerMovement) => {
      if (!hikerPlacementEditable || !selectedHikerId) return;
      setPlacedHikers((prev) =>
        prev.map((hiker) => (hiker.id === selectedHikerId ? { ...hiker, movement } : hiker))
      );
    },
    [hikerPlacementEditable, selectedHikerId]
  );

  const onRemoveHiker = useCallback(
    (hikerId: string) => {
      if (!hikerPlacementEditable) return;
      setPlacedHikers((prev) => prev.filter((hiker) => hiker.id !== hikerId));
      setSelectedHikerId((current) => (current === hikerId ? null : current));
    },
    [hikerPlacementEditable]
  );

  const onClearHikers = useCallback(() => {
    if (!hikerPlacementEditable) return;
    nextHikerNumberRef.current = 1;
    setPlacedHikers([]);
    setSelectedHikerId(null);
    setIsPlacingHiker(false);
  }, [hikerPlacementEditable]);

  return (
    <div className="control-page">
      <TopBar progress={progress} />

      <main className="control-layout">
        <MapPanel
          defaultCenter={DEFAULT_CENTER}
          defaultZoom={DEFAULT_ZOOM}
          mapCenter={mapCenter}
          selectedBounds={selectedBounds}
          missionBounds={mission?.bounds}
          gridShape={mission?.grid_shape}
          setupStage={setupStage}
          missionActive={missionActive}
          validDrones={validDrones}
          targets={targets}
          placedHikers={placedHikers}
          hikerPlacementEditable={hikerPlacementEditable}
          hikerPlacementMode={isPlacingHiker}
          getHikerLabel={getHikerLabel}
          getPlacedHikerLabel={getPlacedHikerLabel}
          setSelectedDrone={setSelectedDrone}
          onSelectHiker={setSelectedHikerId}
          onPlaceHiker={onPlaceHiker}
          onMoveHiker={onMoveHiker}
          droneTrails={droneTrails}
          pmvHeatmap={pmvHeatmap}
          selectedAlgorithm={selectedAlgorithm}
          onSelectArea={onSelectArea}
          onSelectTemporaryRegion={onSelectTemporaryRegion}
          temporaryRegionBounds={temporaryRegionBounds}
          temporaryRegionCells={temporaryRegionCells}
          operatorLabelGrid={mission?.operator_label_grid}
          searchableMask={mission?.searchable_mask}
          showLabelledRegions={showLabelledRegions}
          probabilityGrid={mission?.probability_grid}
          showProbabilityHeatmap={showProbabilityHeatmap}
        />

        <aside className="left-rail">
          <OperatorStatusPanel
            elapsedSeconds={elapsedSeconds}
            droneCount={validDroneCount}
            missionComplete={missionComplete}
            missionStatus={missionStatus}
            placedHikerCount={placedHikers.length}
            progress={progress}
            selectedBounds={selectedBounds}
            targets={targets}
            telemetryMode={telemetryMode}
          />
          <LegendPanel />
        </aside>

        <aside className="right-rail">
          <NavigationPanel
            setupStage={setupStage}
            topLeftLat={topLeftLat}
            topLeftLon={topLeftLon}
            bottomRightLat={bottomRightLat}
            bottomRightLon={bottomRightLon}
            selectedBounds={selectedBounds}
            gridShape={mission?.grid_shape}
            isValidBounds={isValidBounds}
            missionActive={missionActive}
            missionLocked={missionLocked}
            missionStatus={missionStatus}
            searchAreaConfirmed={selectedBounds != null}
            temporaryRegionSelectedCellCount={temporaryRegionCells.length}
            temporaryRegionLabel={temporaryRegionLabel}
            showLabelledRegions={showLabelledRegions}
            showProbabilityHeatmap={showProbabilityHeatmap}
            probabilityMapAvailable={probabilityMapAvailable}
            searchAreaEditingDisabled={searchAreaEditingDisabled}
            onTopLeftLatChange={onTopLeftLatChange}
            onTopLeftLonChange={onTopLeftLonChange}
            onBottomRightLatChange={onBottomRightLatChange}
            onBottomRightLonChange={onBottomRightLonChange}
            onSetSearchArea={onSetSearchArea}
            onConfigureProbabilityMap={configureProbabilityMap}
            onShowLabelledRegionsChange={setShowLabelledRegions}
            onShowProbabilityHeatmapChange={setShowProbabilityHeatmap}
            onTemporaryRegionLabelChange={setTemporaryRegionLabel}
            onApplyTemporaryRegion={onApplyTemporaryRegion}
            onCancelTemporaryRegion={clearTemporaryRegionSelection}
            onBackFromLabelRegions={backFromLabelRegions}
            onConfirmLabelledRegions={handleConfirmLabelledRegions}
            onBackFromReview={backFromReview}
          />
          <ActionsPanel
            selectedBounds={selectedBounds}
            missionStatus={missionStatus}
            missionActive={missionActive}
            missionLocked={missionLocked}
            validDroneCount={validDroneCount}
            mission={mission}
            setupStage={setupStage}
            canStartMission={canStartMission}
            startMissionHelperText={startMissionHelperText}
            selectedAlgorithm={selectedAlgorithm}
            algorithmOptions={algorithmOptions}
            onAlgorithmChange={onAlgorithmChange}
            onStartMission={handleStartMission}
            onStopMission={stopMission}
            onRecallDrones={recallDrones}
            onResetMission={onResetMission}
          />
          <HikerSetupPanel
            selectedBoundsReady={selectedBounds != null}
            hikers={placedHikers}
            editable={hikerPlacementEditable}
            placementMode={isPlacingHiker}
            getHikerLabel={getPlacedHikerLabel}
            onAddHiker={onAddHiker}
            onSelectHiker={setSelectedHikerId}
            onRemoveHiker={onRemoveHiker}
            onClearHikers={onClearHikers}
          />
          <FoundHikersPanel hikers={foundHikersSorted} getHikerLabel={getHikerLabel} />
        </aside>
      </main>

      <DroneModal drone={selectedDrone} onClose={() => setSelectedDrone(null)} />
      <HikerModal
        hiker={selectedPlacedHiker}
        label={selectedPlacedHikerLabel}
        editable={hikerPlacementEditable}
        onMovementChange={onHikerMovementChange}
        onClose={() => setSelectedHikerId(null)}
      />
      <SearchSummaryModal
        isOpen={searchSummaryOpen}
        onClose={() => setSearchSummaryOpen(false)}
        targets={completedTargetsSorted}
        getHikerLabel={getHikerLabel}
        onRecall={recallDrones}
        completionElapsedSeconds={completionElapsedSeconds}
        metrics={completedMetrics}
      />
    </div>
  );
}
