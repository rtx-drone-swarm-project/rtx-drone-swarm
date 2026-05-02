export type MissionStatus = "idle" | "running" | "stopped" | "complete";

export type AlgorithmOption = "voronoi" | "voronoi_aco" | "apf" | "sweep" ;

/** Keys supported by backend `ALGORITHMS` — keep in sync with `backend/app/algorithms/__init__.py`. */
export const ALGORITHM_OPTIONS: { value: AlgorithmOption; label: string }[] = [
  { value: "voronoi", label: "Voronoi (Lloyd's)" },
  { value: "voronoi_aco", label: "Voronoi (ACO)" },
  { value: "apf", label: "APF (Potential Fields)" },
  { value: "sweep", label: "Sweep (Voronoi + Lawnmower)" }
];

export function algorithmDisplayLabel(id: AlgorithmOption | string): string {
  const match = ALGORITHM_OPTIONS.find((o) => o.value === id);
  return match?.label ?? id;
}

export type BenchmarkMetricStats = {
  mean: number | null;
  min: number | null;
  max: number | null;
  stddev: number | null;
};

export type BenchmarkAlgorithmSummary = {
  count: number;
  [metric: string]: BenchmarkMetricStats | number;
};

export type BenchmarkSummary = Record<string, BenchmarkAlgorithmSummary>;

export type BenchmarkRun = {
  run_id: string;
  status: "running" | "complete" | "failed" | string;
  created_at?: string;
  completed_at?: string | null;
  total_trials: number;
  completed_trials: number;
  request?: {
    algorithms?: string[];
    iterations?: number;
    drone_count?: number;
    target_count?: number;
    timeout_seconds?: number;
  };
  summary?: BenchmarkSummary;
  error?: string | null;
};

export type BenchmarkRequestPayload = {
  algorithms: AlgorithmOption[];
  iterations: number;
  bounds: Bounds;
  drone_count: number;
  target_count: number;
  timeout_seconds: number;
  seed?: number;
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

export type MissionMetrics = {
  algorithm: string;
  status?: string;
  elapsed_seconds: number;
  completion_elapsed_seconds?: number | null;
  targets_total: number;
  targets_found: number;
  found_at_seconds: number[];
  first_find_seconds?: number | null;
  last_find_seconds?: number | null;
  avg_find_seconds?: number | null;
  coverage_pct: number;
  coverage_rate_per_sec: number;
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
