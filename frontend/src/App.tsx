import { useCallback, useEffect, useMemo, useState } from "react";
import { getApiBase, getApiPort } from "./api/runtime";
import TopBar from "./components/layout/TopBar";
import MapPanel from "./components/map/MapPanel";
import DroneModal from "./components/modals/DroneModal";
import HikerSummaryModal from "./components/modals/HikerSummaryModal";
import AlertsPanel from "./components/panels/AlertsPanel";
import ActionsPanel from "./components/panels/ActionsPanel";
import FoundHikersPanel from "./components/panels/FoundHikersPanel";
import LegendPanel from "./components/panels/LegendPanel";
import NavigationPanel from "./components/panels/NavigationPanel";
import SwarmStatusPanel from "./components/panels/SwarmStatusPanel";
import useMissionActions from "./hooks/useMissionActions";
import useMissionSocket from "./hooks/useMissionSocket";
import type {
  Bounds,
  FoundHiker,
  MissionState,
  SelectedDrone,
  Target,
  TelemetryDrone,
  ValidDrone
} from "./types/mission";
import type { MissionProgressMessage, MissionStatusMessage, TargetFoundMessage, TelemetryMessage } from "./types/ws";
import { normalizeMissionStatus, statusLabel } from "./utils/format";
import { parseCoordinate } from "./utils/validate";

const DEFAULT_CENTER: [number, number] = [33.5, -117.2];
const DEFAULT_ZOOM = 13;

export default function App() {
  const apiPort = getApiPort();
  const apiBase = useMemo(() => getApiBase(apiPort), [apiPort]);

  const [alerts, setAlerts] = useState<string[]>(["System ready."]);
  const [telemetry, setTelemetry] = useState<TelemetryDrone[]>([]);
  const [mission, setMission] = useState<MissionState>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [searchStatus, setSearchStatus] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [targets, setTargets] = useState<Target[]>([]);
  const [foundHikers, setFoundHikers] = useState<FoundHiker[]>([]);
  const [missionLocked, setMissionLocked] = useState(false);
  const [lat, setLat] = useState(DEFAULT_CENTER[0].toFixed(6));
  const [lon, setLon] = useState(DEFAULT_CENTER[1].toFixed(6));
  const [isValidCoord, setIsValidCoord] = useState(true);
  const [mapCenter, setMapCenter] = useState<[number, number] | null>(DEFAULT_CENTER);
  const [mapAutocentered, setMapAutocentered] = useState(false);
  const [selectedBounds, setSelectedBounds] = useState<Bounds | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [selectedDrone, setSelectedDrone] = useState<SelectedDrone>(null);
  const [hikerSummaryOpen, setHikerSummaryOpen] = useState(false);
  const [completedTargets, setCompletedTargets] = useState<Target[]>([]);
  const [summaryMissionId, setSummaryMissionId] = useState<string | number | null>(null);

  const pushAlert = useCallback((message: string) => {
    setAlerts((prev) => [message, ...prev].slice(0, 10));
  }, []);

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

          return normalizedDrone;
        })
        .filter((drone): drone is ValidDrone => drone !== null),
    [telemetry]
  );

  const validDroneCount = validDrones.length;

  useEffect(() => {
    if (normalizeMissionStatus(searchStatus) !== "running") return;
    const interval = window.setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [searchStatus]);

  const onTelemetry = useCallback((message: TelemetryMessage) => {
    const drones = Array.isArray(message.drones) ? message.drones : [];
    setTelemetry(drones);
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
      const statusText = normalizeMissionStatus(typeof message.status === "string" ? message.status : "idle");
      setSearchStatus(statusText);
      if (typeof message.progress === "number") setProgress(statusText === "complete" ? 100 : message.progress);
      if (Array.isArray(message.targets)) setTargets(message.targets);

      if (statusText === "complete") {
        setElapsedSeconds(0);
        setMissionLocked(true);
        pushAlert("Mission completed.");
      } else {
        pushAlert(`Mission ${message.mission_id}: ${statusLabel(statusText)}.`);
      }
    },
    [pushAlert]
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

      if (canStore) {
        setFoundHikers((prev) => {
          if (prev.some((hiker) => String(hiker.id) === String(foundId))) return prev;
          return [...prev, { id: foundId, lat: foundLat, lon: foundLon, foundAt }];
        });
      }

      const latText = Number.isFinite(foundLat) ? foundLat.toFixed(6) : "unknown";
      const lonText = Number.isFinite(foundLon) ? foundLon.toFixed(6) : "unknown";
      pushAlert(`Hiker ${String(foundId)} located at ${latText}, ${lonText}.`);
    },
    [pushAlert]
  );

  useMissionSocket({
    apiPort,
    onConnectedChange: setWsConnected,
    onAlert: pushAlert,
    onTelemetry,
    onMissionStatus,
    onMissionProgress,
    onTargetFound
  });

  const { startMission, stopMission, resetMissionLock } = useMissionActions({
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
  });

  useEffect(() => {
    if (!mission || !targets.length) return;

    const allFound = targets.every((target) => target.status === "found");
    if (!allFound) return;

    if (summaryMissionId === mission.id) return;

    setProgress(100);
    setSearchStatus("complete");
    setMissionLocked(true);
    setElapsedSeconds(0);
    setCompletedTargets(targets);
    setSummaryMissionId(mission.id);
    setHikerSummaryOpen(true);
    pushAlert("All hikers found in current search area.");
    pushAlert("Mission complete. You can review coordinates in the summary modal.");
  }, [mission, pushAlert, summaryMissionId, targets]);

  useEffect(() => {
    if (!targets.length) return;
    setFoundHikers((prev) => {
      const existing = new Set(prev.map((hiker) => String(hiker.id)));
      const discovered = targets
        .filter((target) => target.status === "found" && !existing.has(String(target.id)))
        .map((target) => ({ id: target.id, lat: target.lat, lon: target.lon }));
      return discovered.length ? [...prev, ...discovered] : prev;
    });
  }, [targets]);

  const applyNavigation = useCallback((nextLat: string, nextLon: string) => {
    const latValue = parseCoordinate(nextLat, -90, 90);
    const lonValue = parseCoordinate(nextLon, -180, 180);
    if (latValue == null || lonValue == null) {
      setIsValidCoord(false);
      return;
    }
    setIsValidCoord(true);
    setMapCenter([latValue, lonValue]);
  }, []);

  const onLatitudeChange = useCallback(
    (nextLat: string) => {
      setLat(nextLat);
      applyNavigation(nextLat, lon);
    },
    [applyNavigation, lon]
  );

  const onLongitudeChange = useCallback(
    (nextLon: string) => {
      setLon(nextLon);
      applyNavigation(lat, nextLon);
    },
    [applyNavigation, lat]
  );

  const onSelectArea = useCallback(
    (selectedLat: number, selectedLon: number, bounds: Bounds) => {
      setSelectedBounds(bounds);
      setLat(selectedLat.toFixed(6));
      setLon(selectedLon.toFixed(6));
      setMapCenter([selectedLat, selectedLon]);
      setIsValidCoord(true);
      pushAlert("Marker placed; 100km² search area selected.");
    },
    [pushAlert]
  );

  const normalizedSearchStatus = normalizeMissionStatus(searchStatus);
  const missionActive = normalizedSearchStatus === "running";
  const missionComplete = normalizedSearchStatus === "complete";
  const lostHikerCount = targets.filter((target) => target.status !== "found").length;

  return (
    <div className="control-page">
      <TopBar progress={progress} />

      <main className="control-layout">
        <MapPanel
          defaultCenter={DEFAULT_CENTER}
          defaultZoom={DEFAULT_ZOOM}
          mapCenter={mapCenter}
          selectedBounds={selectedBounds}
          missionActive={missionActive}
          validDrones={validDrones}
          targets={targets}
          setSelectedDrone={setSelectedDrone}
          onSelectArea={onSelectArea}
        />

        <aside className="left-rail">
          <AlertsPanel
            missionComplete={missionComplete}
            normalizedSearchStatus={normalizedSearchStatus}
            selectedBounds={selectedBounds}
            wsConnected={wsConnected}
            alerts={alerts}
          />
          <SwarmStatusPanel
            elapsedSeconds={elapsedSeconds}
            telemetryCount={telemetry.length}
            validDroneCount={validDroneCount}
            missionActive={missionActive}
            searchStatus={searchStatus}
            lostHikerCount={lostHikerCount}
            telemetryMode={telemetryMode}
          />
          <LegendPanel />
        </aside>

        <aside className="right-rail">
          <NavigationPanel
            lat={lat}
            lon={lon}
            isValidCoord={isValidCoord}
            onLatitudeChange={onLatitudeChange}
            onLongitudeChange={onLongitudeChange}
          />
          <ActionsPanel
            selectedBounds={selectedBounds}
            missionActive={missionActive}
            missionLocked={missionLocked}
            validDroneCount={validDroneCount}
            mission={mission}
            onStartMission={startMission}
            onStopMission={stopMission}
            onResetMission={resetMissionLock}
          />
          <FoundHikersPanel hikers={foundHikers} />
        </aside>
      </main>

      <DroneModal drone={selectedDrone} onClose={() => setSelectedDrone(null)} />
      <HikerSummaryModal
        isOpen={hikerSummaryOpen}
        onClose={() => setHikerSummaryOpen(false)}
        targets={completedTargets}
      />
    </div>
  );
}
