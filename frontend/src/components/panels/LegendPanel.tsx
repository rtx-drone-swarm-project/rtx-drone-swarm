import CollapsibleSection from "../common/CollapsibleSection";

export default function LegendPanel() {
  return (
    <CollapsibleSection title="Legend" defaultOpen={true}>
      <div className="legend-item">
        <span className="legend-chip drone patrol" />
        Drone
      </div>
      <div className="legend-item">
        <span className="legend-chip drone finder" />
        Finder drone
      </div>
      <div className="legend-item">
        <span className="legend-chip drone confirmer" />
        Confirmer drone
      </div>
      <div className="legend-item">
        <span className="legend-dot placed-stationary" />
        Placed stationary hiker
      </div>
      <div className="legend-item">
        <span className="legend-dot placed-moving" />
        Placed moving hiker
      </div>
      <div className="legend-item">
        <span className="legend-dot target" />
        Hiker detected / wandering target
      </div>
      <div className="legend-item">
        <span className="legend-dot confirming" />
        Hiker being confirmed
      </div>
      <div className="legend-item">
        <span className="legend-dot found" />
        Hiker found
      </div>
      <div className="legend-item">
        <span className="legend-boundary" />
        Search area boundary
      </div>
      <div className="legend-help">
        Shift-drag to draw area · Drag hiker markers before start · Click drone or hiker for details
      </div>
    </CollapsibleSection>
  );
}
