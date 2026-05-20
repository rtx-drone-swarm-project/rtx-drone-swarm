import { useEffect } from "react";
import { getWsUrl } from "../api/runtime";
import type {
  BenchmarkProgressMessage,
  MissionProgressMessage,
  MissionStatusMessage,
  PmvHeatmapMessage,
  TelemetryMessage,
  TargetFoundMessage
} from "../types/ws";

type UseMissionSocketArgs = {
  apiPort: string;
  onConnectedChange: (connected: boolean) => void;
  onTelemetry: (message: TelemetryMessage) => void;
  onMissionStatus: (message: MissionStatusMessage) => void;
  onMissionProgress: (message: MissionProgressMessage) => void;
  onTargetFound: (message: TargetFoundMessage) => void;
  onPmvHeatmap?: (message: PmvHeatmapMessage) => void;
  onBenchmarkProgress?: (message: BenchmarkProgressMessage) => void;
};

function isMessageWithType(payload: unknown): payload is { type: string } {
  return typeof payload === "object" && payload !== null && "type" in payload;
}

export default function useMissionSocket({
  apiPort,
  onConnectedChange,
  onTelemetry,
  onMissionStatus,
  onMissionProgress,
  onTargetFound,
  onPmvHeatmap,
  onBenchmarkProgress
}: UseMissionSocketArgs) {
  useEffect(() => {
    const ws = new WebSocket(getWsUrl(apiPort));

    ws.onopen = () => {
      onConnectedChange(true);
    };

    ws.onerror = () => {
      console.warn("WebSocket error.");
    };

    ws.onclose = () => {
      onConnectedChange(false);
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
          return;
        }

        if (payload.type === "pmv_heatmap") {
          onPmvHeatmap?.(payload as PmvHeatmapMessage);
          return;
        }

        if (payload.type === "benchmark_progress") {
          onBenchmarkProgress?.(payload as BenchmarkProgressMessage);
        }
      } catch {
        console.warn("Failed to parse websocket payload.");
      }
    };

    return () => ws.close();
  }, [apiPort, onBenchmarkProgress, onConnectedChange, onMissionProgress, onMissionStatus, onPmvHeatmap, onTargetFound, onTelemetry]);
}
