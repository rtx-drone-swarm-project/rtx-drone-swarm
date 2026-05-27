export type AlgorithmOption = string;

export type AlgorithmMetadata = {
  key: AlgorithmOption;
  label: string;
  description?: string | null;
  module?: string;
  class_name?: string;
};

export const DEFAULT_ALGORITHM_OPTIONS: AlgorithmMetadata[] = [
  { value: "voronoi", label: "Voronoi (Lloyd's)" },
  { value: "voronoi_aco", label: "Voronoi (ACO)" },
  { value: "apf", label: "APF (Potential Fields)" },
  { value: "sweep", label: "Sweep (Voronoi + Lawnmower)" }
].map((item) => ({ key: item.value, label: item.label }));

export function algorithmDisplayLabel(id: AlgorithmOption | string, options = DEFAULT_ALGORITHM_OPTIONS): string {
  const match = options.find((o) => o.key === id);
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

export type BenchmarkTrial = {
  id?: number;
  run_id: string;
  algorithm: string;
  iteration: number;
  scenario_seed: number;
  scenario_profile?: string;
  bounds?: Bounds;
  drone_count: number;
  target_count: number;
  timeout_seconds: number;
  elapsed_seconds: number;
  first_find_seconds?: number | null;
  avg_find_seconds?: number | null;
  last_find_seconds?: number | null;
  completion_elapsed_seconds?: number | null;
  coverage_pct: number;
  miss_pct: number;
  redundant_coverage_pct: number;
  coverage_per_drone_second: number;
  hiker_find_rate: number;
  total_distance_traveled_m: number;
  avg_distance_per_drone_m: number;
  max_distance_single_drone_m: number;
  time_to_50_coverage?: number | null;
  time_to_80_coverage?: number | null;
  time_to_95_coverage?: number | null;
  targets_found: number;
  targets_total: number;
  status: string;
  created_at?: string;
};

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
    scenario_profile?: string;
  };
  summary?: BenchmarkSummary;
  trials?: BenchmarkTrial[];
  error?: string | null;
};

export type BenchmarkReportSummaryRow = {
  algorithm: string;
  trials: number;
  success_rate_pct?: number | null;
  partial_success_rate_pct?: number | null;
  timeout_rate_pct?: number | null;
  total_missed_hikers?: number | null;
  mean_targets_found?: number | null;
  median_first_find_seconds?: number | null;
  p90_first_find_seconds?: number | null;
  mean_first_find_seconds?: number | null;
  mean_last_find_seconds?: number | null;
  mean_coverage_pct?: number | null;
  mean_redundant_coverage_pct?: number | null;
  mean_coverage_per_drone_second?: number | null;
  mean_drone_seconds_total?: number | null;
  mean_search_effort_per_find?: number | null;
  mean_distance_per_find_m?: number | null;
  t50_coverage_reach_pct?: number | null;
  mean_t50_coverage_seconds?: number | null;
  t80_coverage_reach_pct?: number | null;
  mean_t80_coverage_seconds?: number | null;
  t95_coverage_reach_pct?: number | null;
  mean_t95_coverage_seconds?: number | null;
};

export type BenchmarkReport = {
  run_id?: string;
  status: string;
  created_at?: string | null;
  completed_at?: string | null;
  completed_trials: number;
  total_trials: number;
  request?: BenchmarkRun["request"];
  metadata: {
    scenario_profiles: string[];
    movement_mix?: { moving_profiles: number; stationary_profiles: number };
    bounds?: Bounds | null;
    bounds_area_km2?: number | null;
    drone_count?: number | null;
    target_count?: number | null;
    timeout_seconds?: number | null;
    notes?: string[];
  };
  summary: BenchmarkReportSummaryRow[];
  series?: Record<string, unknown>;
  outliers?: Array<Record<string, unknown>>;
};

export type BenchmarkRequestPayload = {
  algorithms: string[];
  iterations: number;
  bounds: Bounds;
  drone_count: number;
  target_count: number;
  timeout_seconds: number;
  scenario_profile?: string;
  seed?: number;
};

export type BenchmarkScenarioProfile = {
  key: string;
  label: string;
  description: string;
  targets_move: boolean;
};

export type EntityId = string | number;

export type HikerMovement = "stationary" | "moving";

export type PlacedHiker = {
  id: string;
  lat: number;
  lon: number;
  movement: HikerMovement;
};

export type Bounds = {
  min_lat: number;
  max_lat: number;
  min_lon: number;
  max_lon: number;
};

export type SearchAreaCorners = {
  topLeftLat: number;
  topLeftLon: number;
  bottomRightLat: number;
  bottomRightLon: number;
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
  movement?: HikerMovement;
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
  bounds?: Bounds;
  grid?: Array<[number, number]>;
  grid_shape?: [number, number] | number[];
  probability_grid?: number[];
  operator_label_grid?: number[][];
  searchable_mask?: boolean[][];
  search_area_confirmed?: boolean;
  probability_grid_confirmed?: boolean;
};

export type SetupStage =
  | "search_area"
  | "label_regions"
  | "review_probability_map"
  | "active_mission";

export type ProbabilityRegionLabel =
  | "very_unlikely"
  | "unlikely"
  | "normal"
  | "likely"
  | "very_likely"
  | "excluded";

export type ProbabilityGridCell = [number, number];

export const PROBABILITY_REGION_LABELS = [
  "very_unlikely",
  "unlikely",
  "normal",
  "likely",
  "very_likely",
  "excluded",
] as const;

export const PROBABILITY_REGION_CODE_BY_LABEL: Record<ProbabilityRegionLabel, number> = {
  very_unlikely: 0,
  unlikely: 1,
  normal: 2,
  likely: 3,
  very_likely: 4,
  excluded: 5,
};

export type PreviewProbabilityRegionResponse = {
  cells: ProbabilityGridCell[];
  count: number;
};

export type ApplyProbabilityRegionResponse = {
  operator_label_grid: number[][];
  probability_grid: number[];
  cells: ProbabilityGridCell[];
  count: number;
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

export type MissionHikerInput = {
  id: string;
  lat: number;
  lon: number;
  found: boolean;
  movement?: HikerMovement;
};

export type MissionCreateRequest = {
  name: string;
  bounds: Bounds;
  drones?: MissionDroneInput[];
  hikers?: MissionHikerInput[];
  /** Must match backend-discovered algorithm keys; echoed on the mission until start overrides. */
  algorithm?: AlgorithmOption;
};

export type MissionStartRequest = {
  drones: MissionDroneInput[];
  hikers?: MissionHikerInput[];
  /** Must match backend-discovered algorithm keys. */
  algorithm?: AlgorithmOption;
};
