import CollapsibleSection from "../common/CollapsibleSection";

type NavigationPanelProps = {
  lat: string;
  lon: string;
  isValidCoord: boolean;
  missionActive: boolean;
  onLatitudeChange: (value: string) => void;
  onLongitudeChange: (value: string) => void;
  onSetSearchArea: () => void;
};

export default function NavigationPanel({
  lat,
  lon,
  isValidCoord,
  missionActive,
  onLatitudeChange,
  onLongitudeChange,
  onSetSearchArea
}: NavigationPanelProps) {
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
      <button
        className="action-btn start"
        onClick={onSetSearchArea}
        disabled={!isValidCoord || missionActive}
      >
        Set Search Area
      </button>
      <div className="hint-text">Creates a ~4 km &times; 4 km box centered on these coordinates.</div>
      <div className="hint-text">Tip: right-click any location in Google Maps to copy its coordinates.</div>
    </CollapsibleSection>
  );
}
