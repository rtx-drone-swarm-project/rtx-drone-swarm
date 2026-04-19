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

export function makeTargetCircleIcon(status?: string | null) {
  const normalizedStatus = typeof status === "string" ? status.toLowerCase() : "";
  const isFound = normalizedStatus === "found";
  const isConfirming = normalizedStatus === "confirming";
  const fillColor = isFound ? "#a855f7" : isConfirming ? "#f59e0b" : "#ef4444";
  const accentMarkup = isFound
    ? '<circle cx="24" cy="8" r="4" fill="#7c3aed" stroke="white" stroke-width="2"/><text x="24" y="11" text-anchor="middle" fill="white" font-size="8" font-weight="bold">&#10003;</text>'
    : "";

  return L.divIcon({
    className: "target-label-marker",
    html: `
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
    `,
    iconSize: [32, 32],
    iconAnchor: [16, 16]
  });
}

export function makeTargetTriangleIcon() {
  return makeTargetCircleIcon("found");
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
      <div class="drone-marker-shell ${accentClass}" style="--drone-rotation: ${rotation}deg; --drone-accent: ${accentColor};">
        <div class="drone-hover-label">${safeLabel}</div>
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
