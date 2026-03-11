import CollapsibleSection from "../common/CollapsibleSection";

export default function LegendPanel() {
  return (
    <CollapsibleSection title="Legend" defaultOpen={true}>
      <div className="legend-item">
        <span className="legend-dot drone" />
        Drone (patrol)
      </div>
      <div className="legend-item">
        <span className="legend-dot finder" />
        Drone (finder)
      </div>
      <div className="legend-item">
        <span className="legend-dot confirmer" />
        Drone (confirm)
      </div>
      <div className="legend-item">
        <span className="legend-dot target" />
        Target / Hiker
      </div>
      <div className="legend-item">
        <span className="legend-triangle" />
        Target found
      </div>
      <div className="legend-help">
        <strong>How to use</strong>
        <ul>
          <li>Click map to select area</li>
          <li>Pan map by dragging</li>
          <li>Zoom with mouse wheel</li>
          <li>Click drones for details</li>
        </ul>
      </div>
    </CollapsibleSection>
  );
}
