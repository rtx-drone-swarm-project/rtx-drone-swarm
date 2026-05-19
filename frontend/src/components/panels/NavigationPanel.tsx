import CollapsibleSection from "../common/CollapsibleSection";

type NavigationPanelProps = {
  probabilityMapMode: boolean;
  topLeftLat: string;
  topLeftLon: string;
  bottomRightLat: string;
  bottomRightLon: string;
  isValidBounds: boolean;
  missionActive: boolean;
  searchAreaConfirmed: boolean;
  onTopLeftLatChange: (value: string) => void;
  onTopLeftLonChange: (value: string) => void;
  onBottomRightLatChange: (value: string) => void;
  onBottomRightLonChange: (value: string) => void;
  onSetSearchArea: () => void;
  onConfirmSearchArea: () => void;
  onConfirmLabelledRegions: () => void;
};

export default function NavigationPanel({
  probabilityMapMode,
  topLeftLat,
  topLeftLon,
  bottomRightLat,
  bottomRightLon,
  isValidBounds,
  missionActive,
  searchAreaConfirmed,
  onTopLeftLatChange,
  onTopLeftLonChange,
  onBottomRightLatChange,
  onBottomRightLonChange,
  onSetSearchArea,
  onConfirmSearchArea,
  onConfirmLabelledRegions
}: NavigationPanelProps) {
  if (probabilityMapMode) {
    return (
      <CollapsibleSection title="Navigation">
        <div className="hint-text">Hold Shift and drag on the map to select a region.</div>
        <button
          className="action-btn start"
          onClick={onConfirmLabelledRegions}
          disabled={missionActive}
        >
          Confirm Labelled Regions
        </button>
      </CollapsibleSection>
    );
  }

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
      <button
        className="action-btn start"
        onClick={onConfirmSearchArea}
        disabled={!isValidBounds || !searchAreaConfirmed || missionActive}
      >
        Confirm Search Area
      </button>
    </CollapsibleSection>
  );
}
