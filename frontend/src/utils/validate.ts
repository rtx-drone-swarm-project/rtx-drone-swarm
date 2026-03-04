export function parseCoordinate(value: string, min: number, max: number): number | null {
  const n = Number.parseFloat(value);
  if (!Number.isFinite(n)) return null;
  if (n < min || n > max) return null;
  return n;
}
