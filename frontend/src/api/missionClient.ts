import type {
  AlgorithmOption,
  AlgorithmMetadata,
  ApplyProbabilityRegionResponse,
  BenchmarkRequestPayload,
  BenchmarkRun,
  BenchmarkScenarioProfile,
  MissionCreateRequest,
  MissionStartRequest,
  MissionRecord,
  PreviewProbabilityRegionResponse,
  ProbabilityRegionLabel
} from "../types/mission";

async function requestJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return (await response.json()) as T;
}

export type MissionApiClient = {
  createMission: (payload: MissionCreateRequest) => Promise<MissionRecord>;
  confirmSearchArea: (
    missionId: string | number,
    payload: { bounds: MissionCreateRequest["bounds"]; grid_side?: number }
  ) => Promise<MissionRecord>;
  previewProbabilityRegion: (
    missionId: string | number,
    payload: { rect_bounds: MissionCreateRequest["bounds"] }
  ) => Promise<PreviewProbabilityRegionResponse>;
  applyProbabilityRegion: (
    missionId: string | number,
    payload: { label: ProbabilityRegionLabel; rect_bounds: MissionCreateRequest["bounds"] }
  ) => Promise<ApplyProbabilityRegionResponse>;
  confirmProbabilityGrid: (missionId: string | number) => Promise<MissionRecord>;
  reopenProbabilityGrid: (missionId: string | number) => Promise<MissionRecord>;
  startMission: (
    missionId: string | number,
    payload?: MissionStartRequest
  ) => Promise<MissionRecord>;
  stopMission: (missionId: string | number) => Promise<MissionRecord>;
  deleteMission: (missionId: string | number) => Promise<void>;
  listAlgorithms: () => Promise<{ algorithms: AlgorithmMetadata[] }>;
  startBenchmark: (payload: BenchmarkRequestPayload) => Promise<BenchmarkRun>;
  stopBenchmark: (runId: string) => Promise<BenchmarkRun | { run_id: string; stopping: boolean }>;
  getBenchmarkRun: (runId: string) => Promise<BenchmarkRun>;
  listBenchmarkRuns: () => Promise<{ runs: BenchmarkRun[] }>;
  listBenchmarkScenarios: () => Promise<{ scenarios: BenchmarkScenarioProfile[] }>;
  recallMission: (missionId: string | number) => Promise<MissionRecord>;
  resetMission: (missionId: string | number) => Promise<MissionRecord>;
};

export function createMissionClient(apiBase: string): MissionApiClient {
  return {
    createMission: (payload) =>
      requestJson<MissionRecord>(`${apiBase}/missions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }),

    confirmSearchArea: (missionId, payload) =>
      requestJson<MissionRecord>(`${apiBase}/missions/${missionId}/confirm-search-area`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }),

    previewProbabilityRegion: (missionId, payload) =>
      requestJson<PreviewProbabilityRegionResponse>(`${apiBase}/missions/${missionId}/probability-grid/preview-region`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }),

    applyProbabilityRegion: (missionId, payload) =>
      requestJson<ApplyProbabilityRegionResponse>(`${apiBase}/missions/${missionId}/probability-grid/apply-region`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }),

    confirmProbabilityGrid: (missionId) =>
      requestJson<MissionRecord>(`${apiBase}/missions/${missionId}/probability-grid/confirm`, {
        method: "POST"
      }),

    reopenProbabilityGrid: (missionId) =>
      requestJson<MissionRecord>(`${apiBase}/missions/${missionId}/probability-grid/reopen`, {
        method: "POST"
      }),

    startMission: (missionId, payload) => {
      const normalizedPayload =
        typeof payload === "string"
          ? { algorithm: payload }
          : payload;

      return requestJson<MissionRecord>(`${apiBase}/missions/${missionId}/start`, {
        method: "POST",
        ...(normalizedPayload
          ? {
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(normalizedPayload)
            }
          : {})
      });
    },

    stopMission: (missionId) =>
      requestJson<MissionRecord>(`${apiBase}/missions/${missionId}/stop`, {
        method: "POST"
      }),

    deleteMission: (missionId) =>
      requestJson<void>(`${apiBase}/missions/${missionId}`, {
        method: "DELETE"
      }),

    listAlgorithms: () => requestJson<{ algorithms: AlgorithmMetadata[] }>(`${apiBase}/algorithms`),

    startBenchmark: (payload) =>
      requestJson<BenchmarkRun>(`${apiBase}/benchmark`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      }),

    stopBenchmark: (runId) =>
      requestJson<BenchmarkRun | { run_id: string; stopping: boolean }>(`${apiBase}/benchmark/${runId}/stop`, {
        method: "POST"
      }),

    getBenchmarkRun: (runId) =>
      requestJson<BenchmarkRun>(`${apiBase}/benchmark/${runId}`),

    listBenchmarkRuns: () => requestJson<{ runs: BenchmarkRun[] }>(`${apiBase}/benchmark/runs`),

    listBenchmarkScenarios: () =>
      requestJson<{ scenarios: BenchmarkScenarioProfile[] }>(`${apiBase}/benchmark/scenarios`),

    recallMission: (missionId) =>
      requestJson<MissionRecord>(`${apiBase}/missions/${missionId}/recall`, {
        method: "POST"
      }),

    resetMission: (missionId) =>
      requestJson<MissionRecord>(`${apiBase}/missions/${missionId}/reset`, {
        method: "POST"
      }),
  };
}
