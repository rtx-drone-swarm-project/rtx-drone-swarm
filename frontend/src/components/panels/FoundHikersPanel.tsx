import type { FoundHiker } from "../../types/mission";
import { formatSeconds } from "../../utils/format";
import CollapsibleSection from "../common/CollapsibleSection";

type FoundHikersPanelProps = {
  hikers: FoundHiker[];
};

export default function FoundHikersPanel({ hikers }: FoundHikersPanelProps) {
  if (!hikers.length) return null;

  return (
    <CollapsibleSection title={`Found Hikers (${hikers.length})`} defaultOpen={true}>
      <div className="found-hiker-list">
        {hikers.map((hiker) => (
          <div key={String(hiker.id)} className="found-hiker-item">
            <div className="found-hiker-title">Hiker {String(hiker.id)}</div>
            <div className="found-hiker-coords">
              Lat: {hiker.lat.toFixed(6)} | Lng: {hiker.lon.toFixed(6)}
            </div>
            <div className="found-hiker-time">Found at {formatSeconds(hiker.foundAt)}</div>
          </div>
        ))}
      </div>
    </CollapsibleSection>
  );
}
