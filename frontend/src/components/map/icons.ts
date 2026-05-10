import L from "leaflet";

function escapeHtml(value: string) {
  return value.replace(/[&<>"']/g, (char) => {
    if (char === "&") return "&amp;";
    if (char === "<") return "&lt;";
    if (char === ">") return "&gt;";
    if (char === '"') return "&quot;";
    return "&#39;";
  });
}

export function makeTargetCircleIcon(label: string, status?: string | null) {
  const normalizedStatus = typeof status === "string" ? status.toLowerCase() : "";
  const isFound = normalizedStatus === "found";
  const isConfirming = normalizedStatus === "confirming";
  const safeLabel = escapeHtml(label);
  const fillColor = isFound ? "#a855f7" : isConfirming ? "#f59e0b" : "#ef4444";
  const accentMarkup = isFound
    ? '<circle cx="24" cy="8" r="4" fill="#7c3aed" stroke="white" stroke-width="2"/><text x="24" y="11" text-anchor="middle" fill="white" font-size="8" font-weight="bold">&#10003;</text>'
    : "";

  return L.divIcon({
    className: "target-label-marker",
    html: `
      <div class="target-marker-shell" style="--marker-label-bg-start: ${fillColor}; --marker-label-bg-end: ${fillColor};">
        <div class="map-hover-label">${safeLabel}</div>
        <div class="target-icon-wrap">
          <svg width="32" height="32" viewBox="0 0 32 32" class="target-icon-svg">
            <circle cx="16" cy="10" r="5" fill="${fillColor}" stroke="white" stroke-width="2" />
            <path
              d="M 16 15 L 16 24 M 11 19 L 21 19 M 16 24 L 12 28 M 16 24 L 20 28"
              stroke="${fillColor}"
              stroke-width="3"
              stroke-linecap="round"
              fill="none"
            />
            <path
              d="M 16 15 L 16 24 M 11 19 L 21 19 M 16 24 L 12 28 M 16 24 L 20 28"
              stroke="white"
              stroke-width="1.5"
              stroke-linecap="round"
              fill="none"
            />
            ${accentMarkup}
          </svg>
        </div>
      </div>
    `,
    iconSize: [32, 32],
    iconAnchor: [16, 16]
  });
}

export function makePlacedHikerIcon(label: string, movement: "stationary" | "moving", locked = false) {
  const safeLabel = escapeHtml(label);
  const fillColor = locked ? "#64748b" : movement === "moving" ? "#f97316" : "#22c55e";
  const accentMarkup =
    movement === "moving"
      ? '<circle cx="24" cy="8" r="4" fill="#f97316" stroke="white" stroke-width="2"/><text x="24" y="11" text-anchor="middle" fill="white" font-size="8" font-weight="bold">&#8594;</text>'
      : '<circle cx="24" cy="8" r="4" fill="#22c55e" stroke="white" stroke-width="2"/><text x="24" y="11" text-anchor="middle" fill="white" font-size="9" font-weight="bold">&#9679;</text>';

  return L.divIcon({
    className: "placed-hiker-label-marker",
    html: `
      <div class="target-marker-shell placed-hiker-marker ${locked ? "is-locked" : ""}" style="--marker-label-bg-start: ${fillColor}; --marker-label-bg-end: ${fillColor};">
        <div class="map-hover-label">${safeLabel}</div>
        <div class="target-icon-wrap">
          <svg width="32" height="32" viewBox="0 0 32 32" class="target-icon-svg">
            <circle cx="16" cy="10" r="5" fill="${fillColor}" stroke="white" stroke-width="2" />
            <path
              d="M 16 15 L 16 24 M 11 19 L 21 19 M 16 24 L 12 28 M 16 24 L 20 28"
              stroke="${fillColor}"
              stroke-width="3"
              stroke-linecap="round"
              fill="none"
            />
            <path
              d="M 16 15 L 16 24 M 11 19 L 21 19 M 16 24 L 12 28 M 16 24 L 20 28"
              stroke="white"
              stroke-width="1.5"
              stroke-linecap="round"
              fill="none"
            />
            ${accentMarkup}
          </svg>
        </div>
      </div>
    `,
    iconSize: [32, 32],
    iconAnchor: [16, 16]
  });
}

export function makeTargetTriangleIcon() {
  return makeTargetCircleIcon("Hiker", "found");
}

export function makeCentroidIcon(label: string, phase?: string | null) {
  const normalizedPhase = typeof phase === "string" ? phase.toLowerCase() : "";
  const isReached = normalizedPhase === "sweeping" || normalizedPhase === "complete";
  const phaseLabel =
    normalizedPhase === "en_route"
      ? "en route"
      : normalizedPhase === "sweeping"
        ? "sweeping"
        : normalizedPhase === "complete"
          ? "complete"
          : "";
  const caption = phaseLabel ? `${label} - ${phaseLabel}` : label;
  const safeLabel = escapeHtml(caption);
  const color = isReached ? "#22c55e" : "#60a5fa";
  return L.divIcon({
    className: "sweep-centroid-marker",
    html: `
      <div style="position: relative; width: 20px; height: 20px;" aria-label="${safeLabel}">
        <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
          <circle cx="10" cy="10" r="7" fill="none" stroke="${color}" stroke-width="2" stroke-dasharray="3 2" />
          <circle cx="10" cy="10" r="2" fill="${color}" />
          <line x1="10" y1="0" x2="10" y2="5" stroke="${color}" stroke-width="1.5" />
          <line x1="10" y1="15" x2="10" y2="20" stroke="${color}" stroke-width="1.5" />
          <line x1="0" y1="10" x2="5" y2="10" stroke="${color}" stroke-width="1.5" />
          <line x1="15" y1="10" x2="20" y2="10" stroke="${color}" stroke-width="1.5" />
        </svg>
        <div style="position: absolute; top: 20px; left: 50%; transform: translateX(-50%); min-width: 104px; text-align: center; font-size: 10px; font-weight: 700; color: ${color}; text-shadow: 0 0 3px rgba(0,0,0,0.8); white-space: nowrap;">${safeLabel}</div>
      </div>
    `,
    iconSize: [104, 34],
    iconAnchor: [10, 10]
  });
}

export function makeDroneIcon(label: string, role?: string | null, heading?: number) {
  const normalizedRole = typeof role === "string" ? role.toLowerCase() : "";
  const safeLabel = escapeHtml(label);
  const rotation = Number.isFinite(heading) ? heading : 0;
  const accentColor = normalizedRole === "finder" ? "#3b82f6" : normalizedRole === "confirmer" ? "#f59e0b" : "#34d399";
  const accentClass =
    normalizedRole === "finder"
      ? "role-finder"
      : normalizedRole === "confirmer"
        ? "role-confirmer"
        : "role-default";

  return L.divIcon({
    className: "drone-label-marker",
    html: `
      <div class="drone-marker-shell ${accentClass}" style="--drone-rotation: ${rotation}deg; --drone-accent: ${accentColor}; --marker-label-bg-start: ${accentColor}; --marker-label-bg-end: ${accentColor};">
        <div class="map-hover-label">${safeLabel}</div>
        <div class="drone-icon-wrap">
          <svg width="36" height="36" viewBox="0 0 36 36" class="drone-icon-svg" aria-hidden="true">
            <polygon points="18,4 25,26 18,21 11,26" fill="#31c46d" stroke="white" stroke-width="2.35" />
            <line x1="11" y1="14" x2="5" y2="14" stroke="white" stroke-width="2.2" stroke-linecap="round" />
            <line x1="25" y1="14" x2="31" y2="14" stroke="white" stroke-width="2.2" stroke-linecap="round" />
            <circle cx="5" cy="14" r="3.15" fill="var(--drone-accent)" stroke="white" stroke-width="1.8" />
            <circle cx="31" cy="14" r="3.15" fill="var(--drone-accent)" stroke="white" stroke-width="1.8" />
            <path d="M 16.5 8.5 L 18 6 L 19.5 8.5" fill="none" stroke="white" stroke-width="1.7" stroke-linecap="round" />
          </svg>
        </div>
      </div>
    `,
    iconSize: [44, 52],
    iconAnchor: [22, 18]
  });
}
