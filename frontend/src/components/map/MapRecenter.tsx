import { useEffect } from "react";
import { useMap } from "react-leaflet";

type MapRecenterProps = {
  center: [number, number] | null;
};

export default function MapRecenter({ center }: MapRecenterProps) {
  const map = useMap();

  useEffect(() => {
    if (!center) return;
    map.flyTo(center, map.getZoom(), { duration: 0.7 });
  }, [center, map]);

  return null;
}
