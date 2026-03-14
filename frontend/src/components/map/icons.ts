import L from "leaflet";

export function makeTargetCircleIcon() {
  return L.divIcon({
    className: "target-label-marker",
    html: `<div class="target-icon-inner"></div>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11]
  });
}

export function makeTargetTriangleIcon() {
  return L.divIcon({
    className: "target-triangle-marker",
    html: `
      <div style="position:relative;width:32px;height:28px;">
        <div style="position:absolute;left:0;top:0;width:0;height:0;border-left:16px solid transparent;border-right:16px solid transparent;border-bottom:28px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,0.35);"></div>
        <div style="position:absolute;left:5px;top:4px;width:0;height:0;border-left:11px solid transparent;border-right:11px solid transparent;border-bottom:20px solid #ef4444;"></div>
      </div>
    `,
    iconSize: [32, 28],
    iconAnchor: [16, 28]
  });
}

export function makeDroneIcon(label: string, role?: string | null) {
  const roleClass =
    role === "finder" ? "drone-icon-finder" : role === "confirmer" ? "drone-icon-confirmer" : "";

  return L.divIcon({
    className: "drone-label-marker",
    html: `<div class="drone-icon-inner ${roleClass}">${label}</div>`,
    iconSize: [34, 34],
    iconAnchor: [17, 17]
  });
}
