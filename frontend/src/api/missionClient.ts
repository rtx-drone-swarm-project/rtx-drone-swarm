import type {
  AlgorithmMetadata,
  BenchmarkRequestPayload,
  BenchmarkRun,
  BenchmarkScenarioProfile,
  MissionCreateRequest,
  MissionRecord
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
  startMission: (missionId: string | number, algorithm?: string) => Promise<MissionRecord>;
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

    startMission: (missionId, algorithm) =>
      requestJson<MissionRecord>(`${apiBase}/missions/${missionId}/start`, {
        method: "POST",
        ...(algorithm
          ? {
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ algorithm })
            }
          : {})
      }),

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
