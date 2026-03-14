import { describe, expect, it } from "vitest";
import { boundsToLeaflet, fixedAreaBounds, kmToLatDelta, kmToLonDelta } from "./geo";

describe("geo utilities", () => {
  it("converts km deltas for latitude and longitude", () => {
    expect(kmToLatDelta(5)).toBeGreaterThan(0);
    expect(kmToLonDelta(5, 33.5)).toBeGreaterThan(0);
  });

  it("produces fixed bounds around a center", () => {
    const centerLat = 33.5;
    const centerLon = -117.2;
    const bounds = fixedAreaBounds(centerLat, centerLon);

    expect(bounds.min_lat).toBeLessThan(centerLat);
    expect(bounds.max_lat).toBeGreaterThan(centerLat);
    expect(bounds.min_lon).toBeLessThan(centerLon);
    expect(bounds.max_lon).toBeGreaterThan(centerLon);
  });

  it("maps bounds to leaflet rectangle tuple", () => {
    const leafletBounds = boundsToLeaflet({
      min_lat: 33,
      max_lat: 34,
      min_lon: -118,
      max_lon: -117
    });

    expect(leafletBounds).toEqual([
      [33, -118],
      [34, -117]
    ]);
  });
});
