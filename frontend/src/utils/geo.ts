import type { Bounds, SearchAreaCorners } from "../types/mission";

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

export function customAreaBounds(centerLat: number, centerLon: number, halfSideKm: number): Bounds {
  const latDelta = kmToLatDelta(halfSideKm);
  const lonDelta = kmToLonDelta(halfSideKm, centerLat);

  return {
    min_lat: centerLat - latDelta,
    max_lat: centerLat + latDelta,
    min_lon: centerLon - lonDelta,
    max_lon: centerLon + lonDelta
  };
}

export function draggedCornersToSearchArea(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number
): SearchAreaCorners {
  return {
    topLeftLat: Math.max(lat1, lat2),
    topLeftLon: Math.min(lon1, lon2),
    bottomRightLat: Math.min(lat1, lat2),
    bottomRightLon: Math.max(lon1, lon2)
  };
}

export function searchAreaCornersToBounds(corners: SearchAreaCorners): Bounds {
  return {
    min_lat: Math.min(corners.topLeftLat, corners.bottomRightLat),
    max_lat: Math.max(corners.topLeftLat, corners.bottomRightLat),
    min_lon: Math.min(corners.topLeftLon, corners.bottomRightLon),
    max_lon: Math.max(corners.topLeftLon, corners.bottomRightLon)
  };
}

export function boundsToSearchAreaCorners(bounds: Bounds): SearchAreaCorners {
  return {
    topLeftLat: bounds.max_lat,
    topLeftLon: bounds.min_lon,
    bottomRightLat: bounds.min_lat,
    bottomRightLon: bounds.max_lon
  };
}

export function boundsToLeaflet(bounds: Bounds): [[number, number], [number, number]] {
  return [
    [bounds.min_lat, bounds.min_lon],
    [bounds.max_lat, bounds.max_lon]
  ];
}

export function estimateBoundsAreaKm2(bounds: Bounds): number {
  const avgLat = (bounds.min_lat + bounds.max_lat) / 2;
  const latKm = Math.abs(bounds.max_lat - bounds.min_lat) * 110.574;
  const lonKm = Math.abs(bounds.max_lon - bounds.min_lon) * 111.32 * Math.max(0.2, Math.cos((avgLat * Math.PI) / 180));

  return latKm * lonKm;
}
