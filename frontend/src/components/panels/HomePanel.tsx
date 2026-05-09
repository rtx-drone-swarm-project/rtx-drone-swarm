import CollapsibleSection from "../common/CollapsibleSection";

type HomePanelProps = {
  lat: string;
  lon: string;
  isValidCoord: boolean;
  disabled?: boolean;
  onLatitudeChange: (value: string) => void;
  onLongitudeChange: (value: string) => void;
  onSetMissionHome: () => void;
};

export default function HomePanel({
  lat,
  lon,
  isValidCoord,
  disabled = false,
  onLatitudeChange,
  onLongitudeChange,
  onSetMissionHome
}: HomePanelProps) {
  return (
    <CollapsibleSection title="Home">
      <label className="field">
        Latitude
        <input
          type="text"
          value={lat}
          placeholder="e.g. 33.5000"
          onChange={(e) => onLatitudeChange(e.target.value)}
          className={isValidCoord ? "" : "invalid"}
          disabled={disabled}
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
          disabled={disabled}
        />
      </label>
      {!isValidCoord && <div className="error-text">Lat: -90..90, Lng: -180..180</div>}

      <button
        className="action-btn start"
        onClick={onSetMissionHome}
        disabled={!isValidCoord || disabled}
      >
        Set Mission Home
      </button>
    </CollapsibleSection>
  );
}
