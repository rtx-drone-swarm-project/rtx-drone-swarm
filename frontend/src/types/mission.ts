export type MissionStatus = "idle" | "running" | "stopped" | "complete";

export type AlgorithmOption = "voronoi" | "voronoi_aco" | "apf" | "sweep" ;

/** Keys supported by backend `ALGORITHMS` — keep in sync with `backend/app/algorithms/__init__.py`. */
export const ALGORITHM_OPTIONS: { value: AlgorithmOption; label: string }[] = [
  { value: "voronoi", label: "Voronoi (Lloyd's)" },
  { value: "voronoi_aco", label: "Voronoi (ACO)" },
  { value: "apf", label: "APF (Potential Fields)" },
  { value: "sweep", label: "Voronoi + Lawnmower Sweep"}
];

export function algorithmDisplayLabel(id: AlgorithmOption | string): string {
  const match = ALGORITHM_OPTIONS.find((o) => o.value === id);
  return match?.label ?? id;
}

export type EntityId = string | number;

export type Bounds = {
  min_lat: number;
  max_lat: number;
  min_lon: number;
  max_lon: number;
};

export type TelemetryDrone = {
  id: EntityId;
  sysid?: number | null;
  lat?: number | string | null;
  lon?: number | string | null;
  alt?: number | string | null;
  heading?: number | string | null;
  groundspeed?: number | string | null;
  telemetry_source?: string | null;
  mode?: string | null;
  armed?: boolean | null;
  status?: string | null;
  target_lat?: number | string | null;
  target_lon?: number | string | null;
  role?: string | null;
  sweep_centroid?: [number, number] | null;
  sweep_phase?: string | null;
};

export type Target = {
  id: EntityId;
  lat: number;
  lon: number;
  status?: string;
};

export type FoundHiker = {
  id: EntityId;
  lat: number;
  lon: number;
  foundAt?: number;
};

export type MissionRecord = {
  id: EntityId;
  name?: string;
  status?: string;
  progress?: number;
  targets?: Target[];
  algorithm?: string;
};

export type MissionState = MissionRecord | null;

export type SelectedDrone = ValidDrone | null;

export type ValidDrone = {
  id: EntityId;
  sysid?: number | null;
  lat: number;
  lon: number;
  alt?: number;
  heading?: number;
  groundspeed?: number;
  telemetry_source?: string | null;
  mode?: string | null;
  armed?: boolean | null;
  status?: string | null;
  target_lat?: number;
  target_lon?: number;
  role?: string | null;
  sweep_centroid?: [number, number];
  sweep_phase?: string;
};

export type MissionDroneInput = {
  id: EntityId;
  lat: number;
  lon: number;
  sysid?: number | null;
  alt?: number;
  heading?: number;
  groundspeed?: number;
  target_lat?: number;
  target_lon?: number;
  role?: string | null;
};

export type MissionCreateRequest = {
  name: string;
  bounds: Bounds;
  drones: MissionDroneInput[];
  /** Must match backend `ALGORITHMS` keys; echoed on the mission until start overrides. */
  algorithm?: AlgorithmOption;
  hikers?: Array<{
    id: string;
    lat: number;
    lon: number;
    found: boolean;
  }>;
};
