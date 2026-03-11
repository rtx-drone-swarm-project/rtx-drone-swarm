import CollapsibleSection from "../common/CollapsibleSection";

type NavigationPanelProps = {
  lat: string;
  lon: string;
  isValidCoord: boolean;
  onLatitudeChange: (value: string) => void;
  onLongitudeChange: (value: string) => void;
};

export default function NavigationPanel({
  lat,
  lon,
  isValidCoord,
  onLatitudeChange,
  onLongitudeChange
}: NavigationPanelProps) {
  return (
    <CollapsibleSection title="Navigation">
      <label className="field">
        Latitude
        <input
          type="text"
          value={lat}
          onChange={(e) => onLatitudeChange(e.target.value)}
          className={isValidCoord ? "" : "invalid"}
        />
      </label>
      <label className="field">
        Longitude
        <input
          type="text"
          value={lon}
          onChange={(e) => onLongitudeChange(e.target.value)}
          className={isValidCoord ? "" : "invalid"}
        />
      </label>
      {!isValidCoord && <div className="error-text">Lat: -90..90, Lng: -180..180</div>}
    </CollapsibleSection>
  );
}
