import { useEffect, useMemo, useState } from "react";
import { CircleMarker, MapContainer, Marker, Rectangle, TileLayer, useMapEvents } from "react-leaflet";

const DEFAULT_CENTER = [-37.5, 143.2];
const DEFAULT_ZOOM = 12;
const HALF_SIDE_KM = 5; // 10km x 10km = 100 km^2

function kmToLatDelta(km) {
  return km / 110.574;
}

function kmToLonDelta(km, latDeg) {
  const cosLat = Math.max(0.2, Math.cos((latDeg * Math.PI) / 180));
  return km / (111.320 * cosLat);
}

function fixedAreaBounds(centerLat, centerLon) {
  const latDelta = kmToLatDelta(HALF_SIDE_KM);
  const lonDelta = kmToLonDelta(HALF_SIDE_KM, centerLat);
  return {
    min_lat: centerLat - latDelta,
    max_lat: centerLat + latDelta,
    min_lon: centerLon - lonDelta,
    max_lon: centerLon + lonDelta
  };
}

function boundsToLeaflet(bounds) {
  return [
    [bounds.min_lat, bounds.min_lon],
    [bounds.max_lat, bounds.max_lon]
  ];
}

function MapClickSelector({ onSelect }) {
  useMapEvents({
    click: (e) => {
      onSelect(e.latlng.lat, e.latlng.lng);
    }
  });
  return null;
}

function formatElapsed(startedAt) {
  if (!startedAt) return "00:00";
  const sec = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  const mm = String(Math.floor(sec / 60)).padStart(2, "0");
  const ss = String(sec % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

export default function App() {
  const apiBase = useMemo(
    () => `${window.location.protocol}//${window.location.hostname}:8000`,
    []
  );

  const [alerts, setAlerts] = useState(["System ready."]);
  const [telemetry, setTelemetry] = useState([]);
  const [mission, setMission] = useState(null);
  const [missionStartedAt, setMissionStartedAt] = useState(null);
  const [searchStatus, setSearchStatus] = useState("idle");
  const [progress, setProgress] = useState(0);
  const [lat, setLat] = useState(DEFAULT_CENTER[0]);
  const [lon, setLon] = useState(DEFAULT_CENTER[1]);
  const [selectedCenter, setSelectedCenter] = useState(null);
  const [selectedBounds, setSelectedBounds] = useState(null);
  const [elapsed, setElapsed] = useState("00:00");

  function pushAlert(message) {
    setAlerts((prev) => [message, ...prev].slice(0, 10));
  }

  const averageBattery = useMemo(() => {
    const values = telemetry
      .map((d) => d.battery_remaining)
      .filter((x) => typeof x === "number" && x >= 0);
    if (!values.length) return "--";
    return `${Math.round(values.reduce((a, b) => a + b, 0) / values.length)}%`;
  }, [telemetry]);

  useEffect(() => {
    const interval = setInterval(() => {
      setElapsed(formatElapsed(missionStartedAt));
    }, 1000);
    return () => clearInterval(interval);
  }, [missionStartedAt]);

  useEffect(() => {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${scheme}://${window.location.hostname}:8000/ws`);

    ws.onopen = () => pushAlert("WebSocket connected.");
    ws.onerror = () => pushAlert("WebSocket error.");
    ws.onclose = () => pushAlert("WebSocket disconnected.");

    ws.onmessage = (evt) => {
      try {
        const payload = JSON.parse(evt.data);
        if (payload.type === "telemetry") {
          setTelemetry(Array.isArray(payload.drones) ? payload.drones : []);
        } else if (payload.type === "mission_status") {
          setSearchStatus(payload.status || "idle");
          if (typeof payload.progress === "number") setProgress(payload.progress);
          pushAlert(`Mission ${payload.mission_id}: ${payload.status}`);
        } else if (payload.type === "mission_progress") {
          if (typeof payload.progress === "number") setProgress(payload.progress);
        } else if (payload.type === "target_found") {
          pushAlert(
            `Target found by drone ${payload.drone_id} at ${payload.lat?.toFixed(5)}, ${payload.lon?.toFixed(5)}`
          );
        }
      } catch {
        pushAlert("Failed to parse websocket payload.");
      }
    };

    return () => ws.close();
  }, []);

  async function startMission() {
    if (!selectedBounds) {
      pushAlert("Click the map first to place a marker and auto-select 100km².");
      return;
    }
    try {
      const createRes = await fetch(`${apiBase}/missions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: `SAR-${new Date().toISOString()}`,
          bounds: selectedBounds,
          drone_count: 15
        })
      });
      if (!createRes.ok) throw new Error(await createRes.text());
      const created = await createRes.json();
      setMission(created);

      const startRes = await fetch(`${apiBase}/missions/${created.id}/start`, {
        method: "POST"
      });
      if (!startRes.ok) throw new Error(await startRes.text());
      const started = await startRes.json();
      setMission(started);
      setSearchStatus(started.status);
      setProgress(started.progress ?? 0);
      setMissionStartedAt(Date.now());
      pushAlert(`Mission started (${started.id}).`);
    } catch (err) {
      pushAlert(`Start failed: ${err.message}`);
    }
  }

  async function stopMission() {
    if (!mission?.id) {
      pushAlert("No active mission to stop.");
      return;
    }
    try {
      const res = await fetch(`${apiBase}/missions/${mission.id}/stop`, {
        method: "POST"
      });
      if (!res.ok) throw new Error(await res.text());
      const stopped = await res.json();
      setMission(stopped);
      setSearchStatus(stopped.status);
      setProgress(stopped.progress ?? progress);
      pushAlert(`Mission stopped (${stopped.id}).`);
    } catch (err) {
      pushAlert(`Stop failed: ${err.message}`);
    }
  }

  const rectBounds = selectedBounds ? boundsToLeaflet(selectedBounds) : null;

  return (
    <div className="page">
      <header className="header">Website Header</header>
      <div className="progress-wrap">
        <div className="progress-label">
          Mission Progress: {progress.toFixed(1)}% {progress >= 100 ? "(Complete)" : ""}
        </div>
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${Math.min(100, progress)}%` }} />
        </div>
      </div>

      <main className="main">
        <section className="panel alerts">
          <h3>Alerts</h3>
          {alerts.map((a, i) => (
            <div key={`${a}-${i}`} className="alert-row">{a}</div>
          ))}
        </section>

        <section className="panel swarm">
          <h3>Swarm Status</h3>
          <div>Time Elapsed: {elapsed}</div>
          <div>Active Drones: {telemetry.length}</div>
          <div>Search Status: {searchStatus}</div>
          <div>Battery: {averageBattery}</div>
          <div>Latency: live</div>
        </section>

        <section className="panel nav">
          <h3>Navigation</h3>
          <label>
            Latitude
            <input value={lat} onChange={(e) => setLat(e.target.value)} />
          </label>
          <label>
            Longitude
            <input value={lon} onChange={(e) => setLon(e.target.value)} />
          </label>
        </section>

        <section className="panel actions">
          <h3>Actions</h3>
          <button onClick={startMission}>Search Area</button>
          <button className="danger" onClick={stopMission}>Stop Mission</button>
        </section>

        <div className="map-area">
          <MapContainer center={DEFAULT_CENTER} zoom={DEFAULT_ZOOM} zoomControl style={{ height: "100%", width: "100%" }}>
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution="&copy; OpenStreetMap contributors"
            />
            <MapClickSelector
              onSelect={(clat, clon) => {
                setSelectedCenter([clat, clon]);
                setSelectedBounds(fixedAreaBounds(clat, clon));
                setLat(clat.toFixed(6));
                setLon(clon.toFixed(6));
                pushAlert("Marker placed; 100km² search area selected.");
              }}
            />
            {selectedCenter && <Marker position={selectedCenter} />}
            {rectBounds && <Rectangle bounds={rectBounds} pathOptions={{ color: "#3761ff" }} />}
            {telemetry
              .filter((d) => d.lat != null && d.lon != null)
              .map((d) => (
                <CircleMarker
                  key={d.id}
                  center={[d.lat, d.lon]}
                  radius={6}
                  pathOptions={{ color: "#44dd44", fillColor: "#44dd44", fillOpacity: 0.9 }}
                />
              ))}
          </MapContainer>
          <div className="map-label">Map View</div>
        </div>
      </main>
    </div>
  );
}
