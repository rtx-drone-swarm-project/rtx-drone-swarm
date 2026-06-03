export function getApiPort(): string {
  return (import.meta.env.VITE_API_PORT as string | undefined) || "8000";
}

export function getApiBase(apiPort: string): string {
  if (isDefaultBrowserPort(apiPort)) {
    return window.location.origin;
  }
  return `${window.location.protocol}//${window.location.hostname}:${apiPort}`;
}

export function getWsUrl(apiPort: string): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const wsHost = isDefaultBrowserPort(apiPort)
    ? window.location.host
    : `${window.location.hostname}:${apiPort}`;

  return `${scheme}://${wsHost}/ws`;
}

function isDefaultBrowserPort(apiPort: string): boolean {
  if (!apiPort) return true;
  return (
    (window.location.protocol === "https:" && apiPort === "443") ||
    (window.location.protocol === "http:" && apiPort === "80")
  );
}
