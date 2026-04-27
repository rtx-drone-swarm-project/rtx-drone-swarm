import { useState } from "react";
import CollapsibleSection from "../common/CollapsibleSection";

type NavigationPanelProps = {
  lat: string;
  lon: string;
  isValidCoord: boolean;
  missionActive: boolean;
  hasDrones: boolean;
  onLatitudeChange: (value: string) => void;
  onLongitudeChange: (value: string) => void;
  onSetSearchArea: (sideKm: number) => void;
  onPanToDrones: () => void;
};

export default function NavigationPanel({
  lat,
  lon,
  isValidCoord,
  missionActive,
  hasDrones,
  onLatitudeChange,
  onLongitudeChange,
  onSetSearchArea,
  onPanToDrones
}: NavigationPanelProps) {
  const [sideKm, setSideKm] = useState(4);

  const handleSideKmChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = Math.max(1, Math.min(100, Number(e.target.value)));
    setSideKm(Number.isFinite(val) ? val : 4);
  };

  return (
    <CollapsibleSection title="Navigation">
      <label className="field">
        Latitude
        <input
          type="text"
          value={lat}
          placeholder="e.g. 33.5000"
          onChange={(e) => onLatitudeChange(e.target.value)}
          className={isValidCoord ? "" : "invalid"}
        />
      </label>
      <label className="field">
        Longitude
        <input
          type="text"
          value={lon}
          placeholder="e.g. -117.2000"
          onChange={(e) => onLongitudeChange(e.target.value)}
          className={isValidCoord ? "" : "invalid"}
        />
      </label>
      {!isValidCoord && <div className="error-text">Lat: -90..90, Lng: -180..180</div>}

      <label className="field">
        Search Area Size (km)
        <input
          type="number"
          value={sideKm}
          min={1}
          max={100}
          step={1}
          onChange={handleSideKmChange}
          disabled={missionActive}
        />
      </label>

      <button
        className="action-btn start"
        onClick={() => onSetSearchArea(sideKm)}
        disabled={!isValidCoord || missionActive}
      >
        Set Search Area
      </button>
      <div className="hint-text">
        Creates a {sideKm} km &times; {sideKm} km box centered on these coordinates.
      </div>
      <div className="hint-text">Tip: right-click any location in Google Maps to copy its coordinates.</div>

      <button
        className="action-btn reset"
        onClick={onPanToDrones}
        disabled={!hasDrones}
      >
        Pan to Drones
      </button>
      {!hasDrones && <div className="hint-text">No drone positions available yet.</div>}
    </CollapsibleSection>
  );
}
