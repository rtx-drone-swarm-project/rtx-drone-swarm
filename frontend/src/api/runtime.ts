export function getApiPort(): string {
  return (import.meta.env.VITE_API_PORT as string | undefined) || "8000";
}

export function getApiBase(apiPort: string): string {
  return `${window.location.protocol}//${window.location.hostname}:${apiPort}`;
}

export function getWsUrl(apiPort: string): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const wsHost =
    import.meta.env.DEV && typeof window !== "undefined"
      ? window.location.host
      : `${window.location.hostname}:${apiPort}`;

  return `${scheme}://${wsHost}/ws`;
}
