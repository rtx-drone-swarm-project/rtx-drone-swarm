import { useEffect, useRef, useState, type MouseEvent, type PointerEvent } from "react";
import { useMap } from "react-leaflet";
import type { Coordinate, ValidDrone } from "../../types/mission";

type MapControlStackProps = {
  drones: ValidDrone[];
  homeLocation?: Coordinate | null;
};

export default function MapControlStack({ drones, homeLocation }: MapControlStackProps) {
  const map = useMap();
  const hasDrones = drones.length > 0;
  const hasHome = homeLocation != null;
  const [controlsBusy, setControlsBusy] = useState(false);
  const controlsBusyRef = useRef(false);
  const unlockTimerRef = useRef<number | null>(null);

  const clearUnlockTimer = () => {
    if (unlockTimerRef.current == null) return;
    window.clearTimeout(unlockTimerRef.current);
    unlockTimerRef.current = null;
  };

  const unlockControls = () => {
    clearUnlockTimer();
    controlsBusyRef.current = false;
    setControlsBusy(false);
  };

  useEffect(() => () => clearUnlockTimer(), []);

  const getBoundedZoom = (nextZoom: number) => {
    const minZoom = map.getMinZoom();
    const maxZoom = map.getMaxZoom();
    const upperBound = Number.isFinite(maxZoom) ? maxZoom : nextZoom;
    return Math.max(minZoom, Math.min(upperBound, nextZoom));
  };

  const smoothZoom = (delta: number) => {
    runWhenReady("zoomend", 500, () => {
      map.stop();
      map.setZoom(getBoundedZoom(map.getZoom() + delta), { animate: true });
    });
  };

  const flyToDrones = () => {
    if (!hasDrones) return;
    runWhenReady("moveend", 1000, () => {
      map.stop();
      const avgLat = drones.reduce((sum, drone) => sum + drone.lat, 0) / drones.length;
      const avgLon = drones.reduce((sum, drone) => sum + drone.lon, 0) / drones.length;
      map.flyTo([avgLat, avgLon], getBoundedZoom(map.getZoom() + 1), { animate: true, duration: 0.7 });
    });
  };

  const flyToHome = () => {
    if (!homeLocation) return;
    runWhenReady("moveend", 1000, () => {
      map.stop();
      map.flyTo([homeLocation.lat, homeLocation.lon], getBoundedZoom(map.getZoom() + 1), {
        animate: true,
        duration: 0.7
      });
    });
  };

  const runWhenReady = (settledEvent: "zoomend" | "moveend", fallbackMs: number, action: () => void) => {
    if (controlsBusyRef.current) return;

    controlsBusyRef.current = true;
    setControlsBusy(true);

    let unlocked = false;
    const unlock = () => {
      if (unlocked) return;
      unlocked = true;
      map.off(settledEvent, unlock);
      unlockControls();
    };

    map.once(settledEvent, unlock);
    unlockTimerRef.current = window.setTimeout(unlock, fallbackMs);
    action();
  };

  const handleControlClick = (event: MouseEvent<HTMLButtonElement>, action: () => void) => {
    event.preventDefault();
    event.stopPropagation();
    action();
  };

  const stopMapInteraction = (event: MouseEvent<HTMLButtonElement> | PointerEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
  };

  return (
    <div className="map-control-stack" role="group" aria-label="Map controls">
      <button
        type="button"
        className="map-control-btn"
        onPointerDown={stopMapInteraction}
        onPointerUp={stopMapInteraction}
        onMouseDown={stopMapInteraction}
        onMouseUp={stopMapInteraction}
        onDoubleClick={stopMapInteraction}
        onClick={(event) => handleControlClick(event, flyToDrones)}
        title="Pan to drones"
        aria-label="Pan to drones"
        disabled={!hasDrones || controlsBusy}
      >
        <svg viewBox="0 0 24 24" fill="none" width="18" height="18" aria-hidden="true">
          <path
            d="M4 12.25 20 4l-4.2 16-3.25-5.1L7.5 18l-1.25-1.25 3.1-5.05L4 12.25Z"
            fill="currentColor"
          />
        </svg>
      </button>
      <button
        type="button"
        className="map-control-btn"
        onPointerDown={stopMapInteraction}
        onPointerUp={stopMapInteraction}
        onMouseDown={stopMapInteraction}
        onMouseUp={stopMapInteraction}
        onDoubleClick={stopMapInteraction}
        onClick={(event) => handleControlClick(event, flyToHome)}
        title="Pan to home"
        aria-label="Pan to home"
        disabled={!hasHome || controlsBusy}
      >
        <svg viewBox="0 0 24 24" fill="none" width="18" height="18" aria-hidden="true">
          <path
            d="M6.5 10.75 12 6l5.5 4.75V18a1 1 0 0 1-1 1H13v-4h-2v4H7.5a1 1 0 0 1-1-1v-7.25Z"
            fill="currentColor"
          />
          <path d="M4.75 11.5 12 5.25l7.25 6.25" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      <button
        type="button"
        className="map-control-btn"
        onPointerDown={stopMapInteraction}
        onPointerUp={stopMapInteraction}
        onMouseDown={stopMapInteraction}
        onMouseUp={stopMapInteraction}
        onDoubleClick={stopMapInteraction}
        onClick={(event) => handleControlClick(event, () => smoothZoom(1))}
        title="Zoom in"
        aria-label="Zoom in"
        disabled={controlsBusy}
      >
        <svg viewBox="0 0 24 24" fill="none" width="18" height="18" aria-hidden="true">
          <path d="M12 6v12M6 12h12" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
        </svg>
      </button>
      <button
        type="button"
        className="map-control-btn"
        onPointerDown={stopMapInteraction}
        onPointerUp={stopMapInteraction}
        onMouseDown={stopMapInteraction}
        onMouseUp={stopMapInteraction}
        onDoubleClick={stopMapInteraction}
        onClick={(event) => handleControlClick(event, () => smoothZoom(-1))}
        title="Zoom out"
        aria-label="Zoom out"
        disabled={controlsBusy}
      >
        <svg viewBox="0 0 24 24" fill="none" width="18" height="18" aria-hidden="true">
          <path d="M6 12h12" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
        </svg>
      </button>
    </div>
  );
}
