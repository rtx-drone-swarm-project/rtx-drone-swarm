import type { Bounds } from "../types/mission";

export const HALF_SIDE_KM = 2;

export function kmToLatDelta(km: number): number {
  return km / 110.574;
}

export function kmToLonDelta(km: number, latDeg: number): number {
  const cosLat = Math.max(0.2, Math.cos((latDeg * Math.PI) / 180));
  return km / (111.32 * cosLat);
}

export function fixedAreaBounds(centerLat: number, centerLon: number): Bounds {
  const latDelta = kmToLatDelta(HALF_SIDE_KM);
  const lonDelta = kmToLonDelta(HALF_SIDE_KM, centerLat);

  return {
    min_lat: centerLat - latDelta,
    max_lat: centerLat + latDelta,
    min_lon: centerLon - lonDelta,
    max_lon: centerLon + lonDelta
  };
}

export function boundsToLeaflet(bounds: Bounds): [[number, number], [number, number]] {
  return [
    [bounds.min_lat, bounds.min_lon],
    [bounds.max_lat, bounds.max_lon]
  ];
}
