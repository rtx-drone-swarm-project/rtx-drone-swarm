import { useEffect } from "react";
import { getWsUrl } from "../api/runtime";
import type {
  MissionProgressMessage,
  MissionStatusMessage,
  TelemetryMessage,
  TargetFoundMessage
} from "../types/ws";

type UseMissionSocketArgs = {
  apiPort: string;
  onConnectedChange: (connected: boolean) => void;
  onAlert: (message: string) => void;
  onTelemetry: (message: TelemetryMessage) => void;
  onMissionStatus: (message: MissionStatusMessage) => void;
  onMissionProgress: (message: MissionProgressMessage) => void;
  onTargetFound: (message: TargetFoundMessage) => void;
};

function isMessageWithType(payload: unknown): payload is { type: string } {
  return typeof payload === "object" && payload !== null && "type" in payload;
}

export default function useMissionSocket({
  apiPort,
  onConnectedChange,
  onAlert,
  onTelemetry,
  onMissionStatus,
  onMissionProgress,
  onTargetFound
}: UseMissionSocketArgs) {
  useEffect(() => {
    const ws = new WebSocket(getWsUrl(apiPort));

    ws.onopen = () => {
      onConnectedChange(true);
      onAlert("WebSocket connected.");
    };

    ws.onerror = () => onAlert("WebSocket error.");

    ws.onclose = () => {
      onConnectedChange(false);
      onAlert("WebSocket disconnected.");
    };

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as unknown;
        if (!isMessageWithType(payload)) return;

        if (payload.type === "telemetry") {
          onTelemetry(payload as TelemetryMessage);
          return;
        }

        if (payload.type === "mission_status") {
          onMissionStatus(payload as MissionStatusMessage);
          return;
        }

        if (payload.type === "mission_progress") {
          onMissionProgress(payload as MissionProgressMessage);
          return;
        }

        if (payload.type === "target_found") {
          onTargetFound(payload as TargetFoundMessage);
        }
      } catch {
        onAlert("Failed to parse websocket payload.");
      }
    };

    return () => ws.close();
  }, [
    apiPort,
    onAlert,
    onConnectedChange,
    onMissionProgress,
    onMissionStatus,
    onTargetFound,
    onTelemetry
  ]);
}
