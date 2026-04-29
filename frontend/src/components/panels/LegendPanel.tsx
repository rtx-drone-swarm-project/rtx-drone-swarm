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
        Drag to draw area · Scroll to zoom · Click drone for details
      </div>
    </CollapsibleSection>
  );
}
