import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  MapContainer,
  Marker,
  Rectangle,
  TileLayer,
  Tooltip,
  useMap,
  useMapEvents
} from "react-leaflet";
import L from "leaflet";

type Bounds = {
  min_lat: number;
  max_lat: number;
  min_lon: number;
  max_lon: number;
};

type TelemetryDrone = {
  id: string | number;
  lat?: number | string | null;
  lon?: number | string | null;
  alt?: number | string | null;
  heading?: number | string | null;
  battery_remaining?: number | null;
  target_lat?: number;
  target_lon?: number;
  role?: string | null;
};

type Target = {
  id: string | number;
  lat: number;
  lon: number;
  status?: string;
};

type MissionState = {
  id: string | number;
  status?: string;
  progress?: number;
  targets?: Target[];
} | null;

type SelectedDrone = {
  id: string | number;
  battery: string;
} | null;

type ValidDrone = {
  id: string | number;
  lat: number;
  lon: number;
  alt?: number;
  heading?: number;
  battery_remaining?: number | null;
  role?: string | null;
};

type WsMessage =
  | { type: "telemetry"; drones?: TelemetryDrone[] }
  | { type: "mission_status"; status?: string; progress?: number; targets?: Target[]; mission_id?: string | number }
  | { type: "mission_progress"; progress?: number }
  | { type: "target_found"; drone_id?: string | number; lat?: number; lon?: number }
  | { type?: string; [key: string]: unknown };

const DEFAULT_CENTER: [number, number] = [33.5, -117.2];
const DEFAULT_ZOOM = 13;
const HALF_SIDE_KM = 5; // 10km x 10km = 100 km^2 (use 0.5 for 1km^2 demo)

function makeTargetCircleIcon() {
  return L.divIcon({
    className: "target-label-marker",
    html: `<div class="target-icon-inner"></div>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11]
  });
}

function makeTargetTriangleIcon() {
  return L.divIcon({
    className: "target-triangle-marker",
    html: `
      <div style="position:relative;width:32px;height:28px;">
        <div style="position:absolute;left:0;top:0;width:0;height:0;border-left:16px solid transparent;border-right:16px solid transparent;border-bottom:28px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,0.35);"></div>
        <div style="position:absolute;left:5px;top:4px;width:0;height:0;border-left:11px solid transparent;border-right:11px solid transparent;border-bottom:20px solid #ef4444;"></div>
      </div>
    `,
    iconSize: [32, 28],
    iconAnchor: [16, 28]
  });
}

function makeDroneIcon(label: string, role?: string | null) {
  const roleClass =
    role === "finder" ? "drone-icon-finder" : role === "confirmer" ? "drone-icon-confirmer" : "";
  return L.divIcon({
    className: "drone-label-marker",
    html: `<div class="drone-icon-inner ${roleClass}">${label}</div>`,
    iconSize: [34, 34],
    iconAnchor: [17, 17]
  });
}

function kmToLatDelta(km: number): number {
  return km / 110.574;
}

function kmToLonDelta(km: number, latDeg: number): number {
  const cosLat = Math.max(0.2, Math.cos((latDeg * Math.PI) / 180));
  return km / (111.320 * cosLat);
}

function fixedAreaBounds(centerLat: number, centerLon: number): Bounds {
  const latDelta = kmToLatDelta(HALF_SIDE_KM);
  const lonDelta = kmToLonDelta(HALF_SIDE_KM, centerLat);
  return {
    min_lat: centerLat - latDelta,
    max_lat: centerLat + latDelta,
    min_lon: centerLon - lonDelta,
    max_lon: centerLon + lonDelta
  };
}

function boundsToLeaflet(bounds: Bounds): [[number, number], [number, number]] {
  return [
    [bounds.min_lat, bounds.min_lon],
    [bounds.max_lat, bounds.max_lon]
  ];
}

function parseCoordinate(value: string, min: number, max: number): number | null {
  const n = Number.parseFloat(value);
  if (!Number.isFinite(n)) return null;
  if (n < min || n > max) return null;
  return n;
}

function formatElapsed(startedAt: number | null): string {
  if (!startedAt) return "00:00";
  const sec = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  const mm = String(Math.floor(sec / 60)).padStart(2, "0");
  const ss = String(sec % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

function CollapsibleSection({
  title,
  children,
  defaultOpen = true
}: {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section className="section-card">
      <button
        type="button"
        className="section-toggle"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
      >
        <span>{title}</span>
        <span className="section-chevron">{open ? "▴" : "▾"}</span>
      </button>
      {open && <div className="section-body">{children}</div>}
    </section>
  );
}

function DroneModal({ drone, onClose }: { drone: SelectedDrone; onClose: () => void }) {
  if (!drone) return null;
  return (
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <div
        className="modal-panel"
        role="dialog"
        aria-modal="true"
        aria-label={`Drone ${drone.id} details`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-header">
          <h2>Drone {drone.id} - Live Feed</h2>
          <button type="button" className="icon-close" onClick={onClose} aria-label="Close dialog">
            &#x2715;
          </button>
        </div>
        <div className="modal-video-placeholder">
          <span className="camera-emoji">&#x1F4F9;</span>
          <div>Drone Camera Feed</div>
          <small>Live view from Drone {drone.id}</small>
        </div>
        <div className="modal-grid">
          <div>
            <label>Altitude</label>
            <strong>{Math.floor(Math.random() * 500 + 100)}m</strong>
          </div>
          <div>
            <label>Speed</label>
            <strong>{Math.floor(Math.random() * 50 + 20)} km/h</strong>
          </div>
          <div>
            <label>Battery</label>
            <strong>{drone.battery}</strong>
          </div>
          <div>
            <label>Status</label>
            <strong className="success">Active</strong>
          </div>
        </div>
      </div>
    </div>
  );
}

function MapClickSelector({
  onSelect,
  enabled
}: {
  onSelect: (lat: number, lon: number) => void;
  enabled: boolean;
}) {
  useMapEvents({
    click: (e) => {
      if (!enabled) return;
      onSelect(e.latlng.lat, e.latlng.lng);
    }
  });
  return null;
}

function MapRecenter({ center }: { center: [number, number] | null }) {
  const map = useMap();
  useEffect(() => {
    if (!center) return;
    map.flyTo(center, map.getZoom(), { duration: 0.7 });
  }, [center, map]);
  return null;
}

export default function App() {
  const apiPort = (import.meta.env.VITE_API_PORT as string | undefined) || "8000";
  const apiBase = useMemo(
    () => `${window.location.protocol}//${window.location.hostname}:${apiPort}`,
    [apiPort]
  );

  const [alerts, setAlerts] = useState<string[]>(["System ready."]);
  const [telemetry, setTelemetry] = useState<TelemetryDrone[]>([]);
  const [mission, setMission] = useState<MissionState>(null);
  const [missionStartedAt, setMissionStartedAt] = useState<number | null>(null);
  const [searchStatus, setSearchStatus] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [targets, setTargets] = useState<Target[]>([]);
  const [lat, setLat] = useState(DEFAULT_CENTER[0].toFixed(6));
  const [lon, setLon] = useState(DEFAULT_CENTER[1].toFixed(6));
  const [isValidCoord, setIsValidCoord] = useState(true);
  const [mapCenter, setMapCenter] = useState<[number, number] | null>(DEFAULT_CENTER);
  const [selectedCenter, setSelectedCenter] = useState<[number, number] | null>(null);
  const [selectedBounds, setSelectedBounds] = useState<Bounds | null>(null);
  const [elapsed, setElapsed] = useState("00:00");
  const [wsConnected, setWsConnected] = useState(false);
  const [selectedDrone, setSelectedDrone] = useState<SelectedDrone>(null);

  function pushAlert(message: string) {
    setAlerts((prev) => [message, ...prev].slice(0, 10));
  }

  const averageBattery = useMemo(() => {
    const values = telemetry
      .map((d) => d.battery_remaining)
      .filter((x): x is number => typeof x === "number" && x >= 0);
    if (!values.length) return "--";
    return `${Math.round(values.reduce((a, b) => a + b, 0) / values.length)}%`;
  }, [telemetry]);

  const validDrones = useMemo<ValidDrone[]>(
    () =>
      telemetry
        .map((d) => {
          const latNum = Number(d?.lat);
          const lonNum = Number(d?.lon);
          if (!Number.isFinite(latNum) || !Number.isFinite(lonNum)) return null;

          const drone: ValidDrone = {
            id: d?.id ?? "unknown",
            lat: latNum,
            lon: lonNum,
            battery_remaining: d.battery_remaining,
            role: typeof d?.role === "string" ? d.role : null
          };
          const altNum = Number(d?.alt);
          const headingNum = Number(d?.heading);
          if (Number.isFinite(altNum)) drone.alt = altNum;
          if (Number.isFinite(headingNum)) drone.heading = headingNum;
          return drone;
        })
        .filter((d): d is ValidDrone => d !== null),
    [telemetry]
  );
  const validDroneCount = validDrones.length;

  useEffect(() => {
    const interval = setInterval(() => {
      setElapsed(formatElapsed(missionStartedAt));
    }, 1000);
    return () => clearInterval(interval);
  }, [missionStartedAt]);

  useEffect(() => {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const wsHost =
      import.meta.env.DEV && typeof window !== "undefined"
        ? window.location.host
        : `${window.location.hostname}:${apiPort}`;
    const ws = new WebSocket(`${scheme}://${wsHost}/ws`);

    ws.onopen = () => {
      setWsConnected(true);
      pushAlert("WebSocket connected.");
    };
    ws.onerror = () => pushAlert("WebSocket error.");
    ws.onclose = () => {
      setWsConnected(false);
      pushAlert("WebSocket disconnected.");
    };

    ws.onmessage = (evt) => {
      try {
        const payload = JSON.parse(evt.data) as WsMessage;
        if (payload.type === "telemetry") {
          setTelemetry(Array.isArray(payload.drones) ? payload.drones : []);
        } else if (payload.type === "mission_status") {
          setSearchStatus(typeof payload.status === "string" ? payload.status : "idle");
          if (typeof payload.progress === "number") setProgress(payload.progress);
          if (Array.isArray(payload.targets)) setTargets(payload.targets);
          pushAlert(`Mission ${payload.mission_id}: ${payload.status}`);
        } else if (payload.type === "mission_progress") {
          if (typeof payload.progress === "number") setProgress(payload.progress);
        } else if (payload.type === "target_found") {
          const latText = typeof payload.lat === "number" ? payload.lat.toFixed(5) : payload.lat;
          const lonText = typeof payload.lon === "number" ? payload.lon.toFixed(5) : payload.lon;
          pushAlert(`Target found by drone ${payload.drone_id} at ${latText}, ${lonText}`);
        }
      } catch {
        pushAlert("Failed to parse websocket payload.");
      }
    };

    return () => ws.close();
  }, [apiPort]);

  async function startMission() {
    if (!selectedBounds) {
      pushAlert("Click the map first to place a marker and auto-select 100km^2.");
      return;
    }

    let missionDrones: Array<Record<string, unknown>> = validDrones.map((d) => ({ ...d }));
    if (validDroneCount < 15) {
      pushAlert(`Warning: only ${validDroneCount} valid drones from telemetry. Generating mock drones...`);
      missionDrones = Array.from({ length: 15 }).map((_, i) => ({
        id: `mock-drone-${i}`,
        lat: selectedBounds.min_lat + Math.random() * (selectedBounds.max_lat - selectedBounds.min_lat),
        lon: selectedBounds.min_lon + Math.random() * (selectedBounds.max_lon - selectedBounds.min_lon),
        alt: 100,
        heading: Math.random() * 360,
        target_lat: selectedBounds.min_lat + Math.random() * (selectedBounds.max_lat - selectedBounds.min_lat),
        target_lon: selectedBounds.min_lon + Math.random() * (selectedBounds.max_lon - selectedBounds.min_lon)
      }));
    }

    try {
      const createRes = await fetch(`${apiBase}/missions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
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
        })
      });
      if (!createRes.ok) throw new Error(await createRes.text());
      const created = (await createRes.json()) as { id: string | number };
      setMission(created);

      const startRes = await fetch(`${apiBase}/missions/${created.id}/start`, { method: "POST" });
      if (!startRes.ok) throw new Error(await startRes.text());
      const started = (await startRes.json()) as MissionState;
      setMission(started);
      setSearchStatus(started?.status ?? "idle");
      setProgress(started?.progress ?? 0);
      if (Array.isArray(started?.targets)) setTargets(started.targets);
      setMissionStartedAt(Date.now());
      pushAlert(`Mission started (${started?.id}).`);
    } catch (err) {
      pushAlert(`Start failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  async function stopMission() {
    if (!mission?.id) {
      pushAlert("No active mission to stop.");
      return;
    }
    try {
      const res = await fetch(`${apiBase}/missions/${mission.id}/stop`, { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      const stopped = (await res.json()) as MissionState;
      setMission(stopped);
      setSearchStatus(stopped?.status ?? "idle");
      setProgress(0);
      pushAlert(`Mission stopped (${stopped?.id}).`);
    } catch (err) {
      pushAlert(`Stop failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  function applyNavigation(nextLat: string, nextLon: string) {
    const latValue = parseCoordinate(nextLat, -90, 90);
    const lonValue = parseCoordinate(nextLon, -180, 180);
    if (latValue == null || lonValue == null) {
      setIsValidCoord(false);
      return;
    }
    setIsValidCoord(true);
    setMapCenter([latValue, lonValue]);
  }

  function onLatitudeChange(nextLat: string) {
    setLat(nextLat);
    applyNavigation(nextLat, lon);
  }

  function onLongitudeChange(nextLon: string) {
    setLon(nextLon);
    applyNavigation(lat, nextLon);
  }

  const missionActive = searchStatus === "running";
  const lostHikerCount = targets.filter((t) => t.status !== "found").length;
  const rectBounds = selectedBounds ? boundsToLeaflet(selectedBounds) : null;

  return (
    <div className="control-page">
      <header className="topbar">
        <h1>Drone Swarm Control Panel</h1>
        <div className="progress-label">Search Progress: {Math.min(100, progress).toFixed(1)}%</div>
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${Math.min(100, progress)}%` }} />
        </div>
      </header>

      <main className="control-layout">
        <div className="map-wrap">
          <MapContainer center={DEFAULT_CENTER} zoom={DEFAULT_ZOOM} zoomControl className="leaflet-map">
            <MapRecenter center={mapCenter} />
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution="&copy; OpenStreetMap contributors"
            />
            <MapClickSelector
              enabled={!missionActive}
              onSelect={(clat, clon) => {
                setSelectedCenter([clat, clon]);
                setSelectedBounds(fixedAreaBounds(clat, clon));
                setLat(clat.toFixed(6));
                setLon(clon.toFixed(6));
                setMapCenter([clat, clon]);
                setIsValidCoord(true);
                pushAlert("Marker placed; 100km² search area selected.");
              }}
            />
            {rectBounds && (
              <Rectangle
                bounds={rectBounds}
                pathOptions={{ color: "#3b82f6", fillOpacity: 0.08, dashArray: "8 8", weight: 2 }}
              />
            )}
            {validDrones.map((d, idx) => {
              const label = `D${typeof d.id === "number" ? d.id : idx + 1}`;
              return (
                <Marker
                  key={`${String(d.id)}-${d.role ?? "normal"}`}
                  position={[d.lat, d.lon]}
                  icon={makeDroneIcon(label, d.role)}
                  eventHandlers={{
                    click: () =>
                      setSelectedDrone({
                        id: d.id,
                        battery: typeof d.battery_remaining === "number" ? `${Math.round(d.battery_remaining)}%` : "--"
                      })
                  }}
                >
                  <Tooltip>{`Drone ${d.id}${d.role ? ` (${d.role})` : ""}`}</Tooltip>
                </Marker>
              );
            })}
            {targets.map((t) => {
              const isFoundOrConfirming = t.status === "found" || t.status === "confirming";
              return (
                <Marker
                  key={`${t.id}-${t.status ?? "wandering"}`}
                  position={[t.lat, t.lon]}
                  icon={isFoundOrConfirming ? makeTargetTriangleIcon() : makeTargetCircleIcon()}
                >
                  <Tooltip>
                    {t.status === "found"
                      ? `Found Hiker ${t.id}`
                      : t.status === "confirming"
                      ? `Confirming Hiker ${t.id}`
                      : t.status === "wandering"
                      ? `Wandering Hiker ${t.id}`
                      : `Target ${t.id}`}
                  </Tooltip>
                </Marker>
              );
            })}
          </MapContainer>
        </div>

        <aside className="left-rail">
          <CollapsibleSection title="Alerts">
            <div className="stack-list">
              {selectedBounds && (
                <div className="alert-chip warning">
                  <span className="alert-icon">&#x26A0;</span>
                  <div>
                    <div className="alert-title">Marker placed</div>
                    <div className="alert-sub">100km&#xB2; search area selected</div>
                  </div>
                </div>
              )}
              <div className={`alert-chip ${wsConnected ? "ok" : "error"}`}>
                <span className="alert-icon">{wsConnected ? "\u{1F7E2}" : "\u{1F534}"}</span>
                <span>WebSocket {wsConnected ? "connected" : "disconnected"}</span>
              </div>
              <div className="alert-log-scroll">
                {alerts.map((a, i) => (
                  <div key={`${a}-${i}`} className="alert-log">
                    {a}
                  </div>
                ))}
              </div>
            </div>
          </CollapsibleSection>

          <CollapsibleSection title="Swarm Status">
            <div className="kv-grid">
              <span>Time Elapsed</span>
              <strong>{elapsed}</strong>
              <span>Active Drones</span>
              <strong>{telemetry.length}</strong>
              <span>Valid Drones</span>
              <strong>{validDroneCount}</strong>
              <span>Search Status</span>
              <strong>{searchStatus}</strong>
              <span>Battery</span>
              <strong>{averageBattery}</strong>
              <span>Latency</span>
              <strong className="success">live</strong>
              <span>Hikers Lost</span>
              <strong>{lostHikerCount}</strong>
            </div>
          </CollapsibleSection>
        </aside>

        <aside className="right-rail">
          <CollapsibleSection title="Navigation">
            <label className="field">
              Latitude
              <input type="text" value={lat} onChange={(e) => onLatitudeChange(e.target.value)} className={isValidCoord ? "" : "invalid"} />
            </label>
            <label className="field">
              Longitude
              <input type="text" value={lon} onChange={(e) => onLongitudeChange(e.target.value)} className={isValidCoord ? "" : "invalid"} />
            </label>
            {!isValidCoord && <div className="error-text">Lat: -90..90, Lng: -180..180</div>}
          </CollapsibleSection>

          <CollapsibleSection title="Actions">
            <button className="action-btn start" onClick={startMission} disabled={!selectedBounds || missionActive}>
              Start Mission
            </button>
            {!selectedBounds && <div className="hint-text">Click the map to select a 100km^2 area.</div>}
            {validDroneCount < 15 && (
              <div className="hint-text warning-text">Warning: only {validDroneCount} valid drones (15 recommended).</div>
            )}
            <button className="action-btn stop" onClick={stopMission} disabled={!mission?.id || !missionActive}>
              Stop Mission
            </button>
          </CollapsibleSection>

          <CollapsibleSection title="Legend" defaultOpen={true}>
            <div className="legend-item">
              <span className="legend-dot drone" />
              Drone
            </div>
            <div className="legend-item">
              <span className="legend-dot target" />
              Target / Hiker
            </div>
            <div className="legend-help">
              <strong>How to use</strong>
              <ul>
                <li>Click map to select area</li>
                <li>Pan map by dragging</li>
                <li>Zoom with mouse wheel</li>
                <li>Click drones for details</li>
              </ul>
            </div>
          </CollapsibleSection>
        </aside>
      </main>

      <DroneModal drone={selectedDrone} onClose={() => setSelectedDrone(null)} />
    </div>
  );
}
