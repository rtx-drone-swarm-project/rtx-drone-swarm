import CollapsibleSection from "../common/CollapsibleSection";

type NavigationPanelProps = {
  topLeftLat: string;
  topLeftLon: string;
  bottomRightLat: string;
  bottomRightLon: string;
  isValidBounds: boolean;
  missionActive: boolean;
  onTopLeftLatChange: (value: string) => void;
  onTopLeftLonChange: (value: string) => void;
  onBottomRightLatChange: (value: string) => void;
  onBottomRightLonChange: (value: string) => void;
  onSetSearchArea: () => void;
};

export default function NavigationPanel({
  topLeftLat,
  topLeftLon,
  bottomRightLat,
  bottomRightLon,
  isValidBounds,
  missionActive,
  onTopLeftLatChange,
  onTopLeftLonChange,
  onBottomRightLatChange,
  onBottomRightLonChange,
  onSetSearchArea
}: NavigationPanelProps) {
  return (
    <CollapsibleSection title="Navigation">
      <label className="field">
        Top-left latitude
        <input
          type="text"
          value={topLeftLat}
          placeholder="e.g. 33.5000"
          onChange={(e) => onTopLeftLatChange(e.target.value)}
          className={isValidBounds ? "" : "invalid"}
        />
      </label>
      <label className="field">
        Top-left longitude
        <input
          type="text"
          value={topLeftLon}
          placeholder="e.g. -117.2000"
          onChange={(e) => onTopLeftLonChange(e.target.value)}
          className={isValidBounds ? "" : "invalid"}
        />
      </label>
      <label className="field">
        Bottom-right latitude
        <input
          type="text"
          value={bottomRightLat}
          placeholder="e.g. 33.4500"
          onChange={(e) => onBottomRightLatChange(e.target.value)}
          className={isValidBounds ? "" : "invalid"}
        />
      </label>
      <label className="field">
        Bottom-right longitude
        <input
          type="text"
          value={bottomRightLon}
          placeholder="e.g. -117.1500"
          onChange={(e) => onBottomRightLonChange(e.target.value)}
          className={isValidBounds ? "" : "invalid"}
        />
      </label>
      {!isValidBounds && (
        <div className="error-text">
          Enter valid corners: lat -90..90, lon -180..180, and the rectangle must have non-zero width and height.
        </div>
      )}

      <button
        className="action-btn start"
        onClick={onSetSearchArea}
        disabled={!isValidBounds || missionActive}
      >
        Set Search Area
      </button>
    </CollapsibleSection>
  );
}
