import type { EntityId, Target, TelemetryDrone } from "./mission";

export type MissionStatus = "idle" | "searching" | "search_complete" | "paused" | "recalling" | "mission_complete";

export type TelemetryMessage = {
  type: "telemetry";
  drones?: TelemetryDrone[];
};

export type MissionStatusMessage = {
  type: "mission_status";
  status: MissionStatus;
  progress?: number;
  targets?: Target[];
  mission_id?: EntityId;
};

export type MissionProgressMessage = {
  type: "mission_progress";
  progress?: number;
};

export type TargetFoundMessage = {
  type: "target_found";
  target_id?: EntityId;
  drone_id?: EntityId;
  lat?: number;
  lon?: number;
  found_at?: number;
};

export type UnknownMessage = {
  type?: string;
  [key: string]: unknown;
};

export type WsMessage =
  | TelemetryMessage
  | MissionStatusMessage
  | MissionProgressMessage
  | TargetFoundMessage
  | UnknownMessage;
