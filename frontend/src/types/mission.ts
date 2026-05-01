export type AlgorithmOption = "voronoi" | "apf" | "sweep";

export type MissionMetrics = {
  algorithm?: string;
  status?: string;
  elapsed_seconds?: number;
  completion_elapsed_seconds?: number | null;
  targets_total?: number;
  targets_found?: number;
  found_at_seconds?: number[];
  first_find_seconds?: number | null;
  last_find_seconds?: number | null;
  avg_find_seconds?: number | null;
  coverage_pct?: number;
  coverage_rate_per_sec?: number;
};

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
  hikers?: Array<{
    id: string;
    lat: number;
    lon: number;
    found: boolean;
  }>;
};
