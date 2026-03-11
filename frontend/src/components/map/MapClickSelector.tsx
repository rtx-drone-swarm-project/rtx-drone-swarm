import { useMapEvents } from "react-leaflet";

type MapClickSelectorProps = {
  onSelect: (lat: number, lon: number) => void;
  enabled: boolean;
};

export default function MapClickSelector({ onSelect, enabled }: MapClickSelectorProps) {
  useMapEvents({
    click: (e) => {
      if (!enabled) return;
      onSelect(e.latlng.lat, e.latlng.lng);
    }
  });

  return null;
}
