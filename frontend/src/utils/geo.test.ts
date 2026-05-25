import { describe, expect, it } from "vitest";
import {
  boundsToLeaflet,
  boundsToSearchAreaCorners,
  draggedCornersToSearchArea,
  estimateBoundsAreaKm2,
  fixedAreaBounds,
  kmToLatDelta,
  kmToLonDelta,
  searchAreaCornersToBounds,
} from "./geo";

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

  it("normalizes dragged corners into top-left and bottom-right corners", () => {
    expect(draggedCornersToSearchArea(33.45, -117.15, 33.55, -117.25)).toEqual({
      topLeftLat: 33.55,
      topLeftLon: -117.25,
      bottomRightLat: 33.45,
      bottomRightLon: -117.15
    });
  });

  it("converts search-area corners into backend bounds", () => {
    expect(
      searchAreaCornersToBounds({
        topLeftLat: 33.55,
        topLeftLon: -117.25,
        bottomRightLat: 33.45,
        bottomRightLon: -117.15
      })
    ).toEqual({
      min_lat: 33.45,
      max_lat: 33.55,
      min_lon: -117.25,
      max_lon: -117.15
    });
  });

  it("converts backend bounds back into panel corners", () => {
    expect(
      boundsToSearchAreaCorners({
        min_lat: 33.45,
        max_lat: 33.55,
        min_lon: -117.25,
        max_lon: -117.15
      })
    ).toEqual({
      topLeftLat: 33.55,
      topLeftLon: -117.25,
      bottomRightLat: 33.45,
      bottomRightLon: -117.15
    });
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

  it("estimates bounded search area in square kilometers", () => {
    const bounds = fixedAreaBounds(33.5, -117.2);

    expect(estimateBoundsAreaKm2(bounds)).toBeGreaterThan(15);
    expect(estimateBoundsAreaKm2(bounds)).toBeLessThan(17);
  });
});
