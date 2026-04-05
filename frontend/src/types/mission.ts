export type MissionStatus = "idle" | "running" | "stopped" | "complete";

export type EntityId = string | number;

export type Bounds = {
  min_lat: number;
  max_lat: number;
  min_lon: number;
  max_lon: number;
};

export type TelemetryDrone = {
  id: EntityId;
  lat?: number | string | null;
  lon?: number | string | null;
  alt?: number | string | null;
  heading?: number | string | null;
  battery_remaining?: number | null;
  telemetry_source?: string | null;
  mode?: string | null;
  armed?: boolean | null;
  target_lat?: number;
  target_lon?: number;
  role?: string | null;
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
};

export type MissionState = MissionRecord | null;

export type SelectedDrone = {
  id: EntityId;
  battery: string;
} | null;

export type ValidDrone = {
  id: EntityId;
  lat: number;
  lon: number;
  alt?: number;
  heading?: number;
  battery_remaining?: number | null;
  role?: string | null;
};

export type MissionDroneInput = {
  id: EntityId;
  lat: number;
  lon: number;
  alt?: number;
  heading?: number;
  target_lat?: number;
  target_lon?: number;
  role?: string | null;
  battery_remaining?: number | null;
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
