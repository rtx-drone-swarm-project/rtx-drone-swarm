import { useEffect, useState } from "react";
import { Rectangle, useMap, useMapEvents } from "react-leaflet";
import type { Bounds } from "../../types/mission";

const MIN_BOX_DEG = 0.001;

type MapBBoxDrawerProps = {
  enabled: boolean;
  onBoundsDrawn: (bounds: Bounds) => void;
};

export default function MapBBoxDrawer({ enabled, onBoundsDrawn }: MapBBoxDrawerProps) {
  const map = useMap();
  const [start, setStart] = useState<[number, number] | null>(null);
  const [current, setCurrent] = useState<[number, number] | null>(null);

  useEffect(() => {
    return () => {
      map.dragging.enable();
      map.getContainer().style.cursor = "";
    };
  }, [map]);

  useEffect(() => {
    if (enabled) return;
    map.dragging.enable();
    map.getContainer().style.cursor = "";
    setStart(null);
    setCurrent(null);
  }, [enabled, map]);

  useMapEvents({
    mousedown(e) {
      if (!enabled) return;
      if (!e.originalEvent.shiftKey) return;
      map.dragging.disable();
      map.getContainer().style.cursor = "crosshair";
      setStart([e.latlng.lat, e.latlng.lng]);
      setCurrent([e.latlng.lat, e.latlng.lng]);
    },
    mousemove(e) {
      if (!start) return;
      setCurrent([e.latlng.lat, e.latlng.lng]);
    },
    mouseup(e) {
      if (!start) return;
      map.dragging.enable();
      map.getContainer().style.cursor = "";

      const bounds: Bounds = {
        min_lat: Math.min(start[0], e.latlng.lat),
        max_lat: Math.max(start[0], e.latlng.lat),
        min_lon: Math.min(start[1], e.latlng.lng),
        max_lon: Math.max(start[1], e.latlng.lng),
      };

      setStart(null);
      setCurrent(null);

      if (
        bounds.max_lat - bounds.min_lat >= MIN_BOX_DEG &&
        bounds.max_lon - bounds.min_lon >= MIN_BOX_DEG
      ) {
        onBoundsDrawn(bounds);
      }
    },
  });

  if (!start || !current) return null;

  const previewBounds: [[number, number], [number, number]] = [
    [Math.min(start[0], current[0]), Math.min(start[1], current[1])],
    [Math.max(start[0], current[0]), Math.max(start[1], current[1])],
  ];

  return (
    <Rectangle
      bounds={previewBounds}
      pathOptions={{ color: "#3b82f6", fillOpacity: 0.08, dashArray: "8 8", weight: 2 }}
    />
  );
}
