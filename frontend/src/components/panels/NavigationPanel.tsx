import CollapsibleSection from "../common/CollapsibleSection";
import {
  PROBABILITY_REGION_LABELS,
  type ProbabilityRegionLabel,
} from "../../types/mission";

const REGION_LABEL_OPTIONS: Array<{ value: ProbabilityRegionLabel; label: string }> = [
  { value: "excluded", label: "Excluded" },
  { value: "very_unlikely", label: "Very unlikely" },
  { value: "unlikely", label: "Unlikely" },
  { value: "normal", label: "Normal" },
  { value: "likely", label: "Likely" },
  { value: "very_likely", label: "Very likely" },
];

const REGION_LABEL_LEGEND: Array<{
  value: ProbabilityRegionLabel;
  label: string;
  className: string;
}> = [
  { value: "very_unlikely", label: "Very unlikely", className: "very-unlikely" },
  { value: "unlikely", label: "Unlikely", className: "unlikely" },
  { value: "likely", label: "Likely", className: "likely" },
  { value: "very_likely", label: "Very likely", className: "very-likely" },
  { value: "excluded", label: "Excluded", className: "excluded" },
];

type NavigationPanelProps = {
  probabilityMapMode: boolean;
  probabilityMapReviewMode: boolean;
  topLeftLat: string;
  topLeftLon: string;
  bottomRightLat: string;
  bottomRightLon: string;
  selectedBounds: {
    min_lat: number;
    max_lat: number;
    min_lon: number;
    max_lon: number;
  } | null;
  gridShape?: [number, number] | number[];
  isValidBounds: boolean;
  missionActive: boolean;
  missionStatus: string;
  searchAreaConfirmed: boolean;
  temporaryRegionSelectedCellCount: number;
  temporaryRegionLabel: ProbabilityRegionLabel | "";
  showLabelledRegions: boolean;
  showProbabilityHeatmap: boolean;
  onTopLeftLatChange: (value: string) => void;
  onTopLeftLonChange: (value: string) => void;
  onBottomRightLatChange: (value: string) => void;
  onBottomRightLonChange: (value: string) => void;
  onSetSearchArea: () => void;
  onConfirmSearchArea: () => void;
  onShowLabelledRegionsChange: (value: boolean) => void;
  onShowProbabilityHeatmapChange: (value: boolean) => void;
  onTemporaryRegionLabelChange: (value: ProbabilityRegionLabel | "") => void;
  onApplyTemporaryRegion: () => void;
  onCancelTemporaryRegion: () => void;
  onConfirmLabelledRegions: () => void;
  onBackToLabelledRegions: () => void;
};

function renderProbabilityLegend() {
  return (
    <div className="probability-legend-block">
      <div className="probability-legend-title">Region label legend</div>
      <div className="probability-legend-list">
        {REGION_LABEL_LEGEND.map((entry) => (
          <div key={entry.value} className="probability-legend-item">
            <span className={`probability-legend-swatch ${entry.className}`} />
            <span>{entry.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function renderHeatmapLegend() {
  return (
    <div className="probability-legend-block heatmap-legend-block">
      <div className="probability-legend-title">Heatmap legend</div>
      <div className="heatmap-legend-scale" aria-hidden="true" />
      <div className="heatmap-legend-labels">
        <span>Low probability</span>
        <span>High probability</span>
      </div>
      <div className="probability-legend-item heatmap-excluded-item">
        <span className="probability-legend-swatch excluded" />
        <span>Excluded</span>
      </div>
    </div>
  );
}

export default function NavigationPanel({
  probabilityMapMode,
  probabilityMapReviewMode,
  topLeftLat,
  topLeftLon,
  bottomRightLat,
  bottomRightLon,
  selectedBounds,
  gridShape,
  isValidBounds,
  missionActive,
  missionStatus,
  searchAreaConfirmed,
  temporaryRegionSelectedCellCount,
  temporaryRegionLabel,
  showLabelledRegions,
  showProbabilityHeatmap,
  onTopLeftLatChange,
  onTopLeftLonChange,
  onBottomRightLatChange,
  onBottomRightLonChange,
  onSetSearchArea,
  onConfirmSearchArea,
  onShowLabelledRegionsChange,
  onShowProbabilityHeatmapChange,
  onTemporaryRegionLabelChange,
  onApplyTemporaryRegion,
  onCancelTemporaryRegion,
  onConfirmLabelledRegions,
  onBackToLabelledRegions,
}: NavigationPanelProps) {
  if (probabilityMapMode) {
    if (probabilityMapReviewMode) {
      const rows = Number(gridShape?.[0] ?? 0);
      const cols = Number(gridShape?.[1] ?? 0);

      return (
        <CollapsibleSection title="Probability Map">
          {selectedBounds && (
            <div className="review-grid">
              <div className="review-title">Search area bounds</div>
              <div className="kv-grid">
                <span>Min latitude</span>
                <strong>{selectedBounds.min_lat.toFixed(6)}</strong>
                <span>Max latitude</span>
                <strong>{selectedBounds.max_lat.toFixed(6)}</strong>
                <span>Min longitude</span>
                <strong>{selectedBounds.min_lon.toFixed(6)}</strong>
                <span>Max longitude</span>
                <strong>{selectedBounds.max_lon.toFixed(6)}</strong>
              </div>
              <div className="review-title">Grid shape</div>
              <div className="kv-grid">
                <span>Rows</span>
                <strong>{Number.isFinite(rows) ? rows : 0}</strong>
                <span>Columns</span>
                <strong>{Number.isFinite(cols) ? cols : 0}</strong>
              </div>
            </div>
          )}
          <label className="panel-toggle">
            <span>Show probability heatmap</span>
            <input
              type="checkbox"
              checked={showProbabilityHeatmap}
              onChange={(e) => onShowProbabilityHeatmapChange(e.target.checked)}
            />
          </label>
          {showProbabilityHeatmap && renderHeatmapLegend()}
          <label className="panel-toggle">
            <span>Show labelled regions</span>
            <input
              type="checkbox"
              checked={showLabelledRegions}
              onChange={(e) => onShowLabelledRegionsChange(e.target.checked)}
            />
          </label>
          {showLabelledRegions && renderProbabilityLegend()}
          <button
            className="action-btn reset"
            onClick={onBackToLabelledRegions}
            disabled={missionActive || missionStatus === "mission_completed"}
          >
            Back to Labelled Regions
          </button>
        </CollapsibleSection>
      );
    }

    const hasTemporarySelection = temporaryRegionSelectedCellCount > 0;

    return (
      <CollapsibleSection title="Navigation">
        {!hasTemporarySelection && (
          <div className="hint-text">Hold Shift and drag on the map to select a region.</div>
        )}
        {hasTemporarySelection && (
          <>
            <div className="kv-grid region-preview-stats">
              <span>Selected cells</span>
              <strong>{temporaryRegionSelectedCellCount}</strong>
            </div>
            <label className="field">
              Region label
              <select
                value={temporaryRegionLabel}
                onChange={(e) => onTemporaryRegionLabelChange(e.target.value as ProbabilityRegionLabel | "")}
                className="algorithm-select"
              >
                <option value="">Select label</option>
                {REGION_LABEL_OPTIONS.filter((option) => PROBABILITY_REGION_LABELS.includes(option.value)).map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="action-btn start"
              onClick={onApplyTemporaryRegion}
              disabled={temporaryRegionLabel === ""}
            >
              Apply Region
            </button>
            <button
              className="action-btn reset"
              onClick={onCancelTemporaryRegion}
            >
              Cancel Selection
            </button>
          </>
        )}
        <label className="panel-toggle">
          <span>Show labelled regions</span>
          <input
            type="checkbox"
            checked={showLabelledRegions}
            onChange={(e) => onShowLabelledRegionsChange(e.target.checked)}
          />
        </label>
        {renderProbabilityLegend()}
        {!hasTemporarySelection && (
          <button
            className="action-btn start"
            onClick={onConfirmLabelledRegions}
            disabled={missionActive}
          >
            Confirm Labelled Regions
          </button>
        )}
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
