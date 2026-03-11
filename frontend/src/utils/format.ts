import type { MissionStatus } from "../types/mission";

export function formatElapsed(seconds: number): string {
  const sec = Math.max(0, Math.floor(seconds));
  const mm = String(Math.floor(sec / 60)).padStart(2, "0");
  const ss = String(sec % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

export function formatSeconds(seconds: number | undefined): string {
  if (typeof seconds !== "number" || seconds < 0) return "--:--";
  const mm = String(Math.floor(seconds / 60)).padStart(2, "0");
  const ss = String(seconds % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

export function normalizeMissionStatus(status: string): MissionStatus {
  const s = status.trim().toLowerCase();
  if (s === "in_progress") return "running";
  if (s === "completed") return "complete";
  if (s === "running" || s === "stopped" || s === "complete") return s;
  return "idle";
}

export function statusLabel(status: string): string {
  const normalized = normalizeMissionStatus(status);
  if (normalized === "running") return "Mission in progress";
  if (normalized === "stopped") return "Mission stopped";
  if (normalized === "complete") return "Mission completed";
  return "Idle";
}
