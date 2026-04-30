import type { MissionCreateRequest, MissionRecord } from "../types/mission";

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
      })
  };
}
