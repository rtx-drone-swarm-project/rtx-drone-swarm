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
  const fillColor = isFound ? "#34d399" : isConfirming ? "#f59e0b" : "#ef4444";
  const accentMarkup = isFound
    ? '<circle cx="24" cy="8" r="4" fill="#10b981" stroke="white" stroke-width="2"/><text x="24" y="11" text-anchor="middle" fill="white" font-size="8" font-weight="bold">&#10003;</text>'
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
  const fillColor = normalizedRole === "finder" ? "#f97316" : normalizedRole === "confirmer" ? "#0ea5e9" : "#22c55e";
  const safeLabel = escapeHtml(label);
  const rotation = Number.isFinite(heading) ? heading : 0;

  return L.divIcon({
    className: "drone-label-marker",
    html: `
      <div class="drone-icon-wrap" style="transform: rotate(${rotation}deg);">
        <svg width="40" height="40" viewBox="0 0 40 40" class="drone-icon-svg">
          <polygon points="20,8 28,32 20,28 12,32" fill="${fillColor}" stroke="white" stroke-width="2" />
          <line x1="12" y1="18" x2="6" y2="18" stroke="white" stroke-width="2" />
          <line x1="28" y1="18" x2="34" y2="18" stroke="white" stroke-width="2" />
          <circle cx="6" cy="18" r="3" fill="${fillColor}" stroke="white" stroke-width="1.5" />
          <circle cx="34" cy="18" r="3" fill="${fillColor}" stroke="white" stroke-width="1.5" />
          <text x="20" y="23" text-anchor="middle" fill="white" font-size="10" font-weight="700">${safeLabel}</text>
        </svg>
      </div>
    `,
    iconSize: [40, 40],
    iconAnchor: [20, 20]
  });
}
