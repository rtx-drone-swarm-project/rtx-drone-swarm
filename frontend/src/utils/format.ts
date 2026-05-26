export function formatElapsed(seconds: number): string {
  return formatDuration(seconds);
}

function formatDuration(seconds: number): string {
  const sec = Math.max(0, Math.floor(seconds));
  const hh = String(Math.floor(sec / 3600)).padStart(2, "0");
  const mm = String(Math.floor((sec % 3600) / 60)).padStart(2, "0");
  const ss = String(sec % 60).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

export function formatSeconds(seconds: number | null | undefined): string {
  if (typeof seconds !== "number" || seconds < 0) return "--:--:--";
  return formatDuration(seconds);
}

export function statusLabel(status: string): string {
  if (status === "searching") return "Searching";
  else if (status === "search_complete") return "Search completed";
  else if (status === "paused") return "Paused";
  else if (status === "recalling") return "Recalling";
  else if (status === "mission_complete") return "Mission completed";
  else return "Idle";
}
