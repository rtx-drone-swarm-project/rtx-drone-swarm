import type { PlacedHiker } from "../../types/mission";
import CollapsibleSection from "../common/CollapsibleSection";

type HikerSetupPanelProps = {
  selectedBoundsReady: boolean;
  hikers: PlacedHiker[];
  editable: boolean;
  placementMode: boolean;
  getHikerLabel: (hiker: PlacedHiker, index: number) => string;
  onAddHiker: () => void;
  onSelectHiker: (hikerId: string) => void;
  onRemoveHiker: (hikerId: string) => void;
  onClearHikers: () => void;
};

export default function HikerSetupPanel({
  selectedBoundsReady,
  hikers,
  editable,
  placementMode,
  getHikerLabel,
  onAddHiker,
  onSelectHiker,
  onRemoveHiker,
  onClearHikers
}: HikerSetupPanelProps) {
  if (!selectedBoundsReady && hikers.length === 0) return null;

  return (
    <CollapsibleSection title={`Hiker Setup${hikers.length ? ` (${hikers.length})` : ""}`} defaultOpen={true}>
      <div className={`hiker-setup ${editable ? "" : "is-disabled"}`}>
        <button
          type="button"
          className={`action-btn hiker-add ${placementMode ? "active" : ""}`}
          onClick={onAddHiker}
          disabled={!editable}
        >
          {placementMode ? "Placing Hikers" : "Add Hiker"}
        </button>
        <div className="hint-text">
          {editable && placementMode
            ? "Click inside the search area to place a hiker."
            : editable
              ? "Add a hiker, then click inside the search area to place it."
              : "Hiker placement is locked while the mission is running or complete."}
        </div>

        {hikers.length > 0 && (
          <div className="hiker-list">
            {hikers.map((hiker, index) => {
              const label = getHikerLabel(hiker, index);
              return (
                <div key={hiker.id} className="hiker-list-item">
                  <button type="button" className="hiker-list-main" onClick={() => onSelectHiker(hiker.id)}>
                    <span>{label}</span>
                    <strong>{hiker.movement === "moving" ? "Moving" : "Stationary"}</strong>
                  </button>
                  <button
                    type="button"
                    className="hiker-remove"
                    onClick={() => onRemoveHiker(hiker.id)}
                    aria-label={`Remove ${label}`}
                    disabled={!editable}
                  >
                    &#x2715;
                  </button>
                </div>
              );
            })}
            <button type="button" className="hiker-clear" onClick={onClearHikers} disabled={!editable}>
              Clear All Hikers
            </button>
          </div>
        )}
      </div>
    </CollapsibleSection>
  );
}
