import type { Bounds, SearchAreaCorners } from "../types/mission";

export function kmToLatDelta(km: number): number {
  return km / 110.574;
}

export function kmToLonDelta(km: number, latDeg: number): number {
  const cosLat = Math.max(0.2, Math.cos((latDeg * Math.PI) / 180));
  return km / (111.32 * cosLat);
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
