import { useCallback, useEffect, useMemo, useState } from "react";
import { createMissionClient } from "../api/missionClient";
import { getApiBase, getApiPort } from "../api/runtime";
import TopBar from "../components/layout/TopBar";
import useMissionSocket from "../hooks/useMissionSocket";
import {
  DEFAULT_ALGORITHM_OPTIONS,
  type AlgorithmMetadata,
  type BenchmarkRun,
  type BenchmarkScenarioProfile,
  type BenchmarkTrial,
  type Bounds
} from "../types/mission";
import type { BenchmarkProgressMessage } from "../types/ws";
import { formatSeconds } from "../utils/format";

const DEFAULT_SCENARIO_PROFILES: BenchmarkScenarioProfile[] = [
  {
    key: "uniform_random",
    label: "Uniform Random",
    description: "Stationary baseline with independent random drone and hiker placement.",
    targets_move: false
  }
];

const BOUNDS_PRESETS: Record<string, { label: string; bounds: Bounds; timeout: number }> = {
  "6km": {
    label: "6 km reference",
    bounds: { min_lat: 33.473, max_lat: 33.527, min_lon: -117.2324, max_lon: -117.1676 },
    timeout: 900
  },
  "10km": {
    label: "10 km reference",
    bounds: { min_lat: 33.455, max_lat: 33.545, min_lon: -117.254, max_lon: -117.146 },
    timeout: 1200
  },
  "12km": {
    label: "12 km reference",
    bounds: { min_lat: 33.446, max_lat: 33.554, min_lon: -117.265, max_lon: -117.135 },
    timeout: 1500
  }
};

const TRIAL_EXPORT_FIELDS: Array<keyof BenchmarkTrial | "source"> = [
  "source",
  "run_id",
  "algorithm",
  "iteration",
  "scenario_seed",
  "scenario_profile",
  "drone_count",
  "target_count",
  "timeout_seconds",
  "elapsed_seconds",
  "first_find_seconds",
  "avg_find_seconds",
  "last_find_seconds",
  "completion_elapsed_seconds",
  "coverage_pct",
  "miss_pct",
  "redundant_coverage_pct",
  "coverage_per_drone_second",
  "hiker_find_rate",
  "total_distance_traveled_m",
  "avg_distance_per_drone_m",
  "max_distance_single_drone_m",
  "time_to_50_coverage",
  "time_to_80_coverage",
  "time_to_95_coverage",
  "targets_found",
  "targets_total",
  "status",
  "created_at"
];

type ImportedTrial = BenchmarkTrial & { source?: string };

type SummaryRow = {
  algorithm: string;
  trials: number;
  successRate: number | null;
  partialSuccess: number | null;
  timeoutRate: number | null;
  missedHikers: number;
  meanCoverage: number | null;
  medianFirstFind: number | null;
  p90FirstFind: number | null;
  meanOverlap: number | null;
  meanDistancePerFind: number | null;
  meanEffortPerFind: number | null;
  meanCoveragePerDroneSecond: number | null;
  t50Reach: number | null;
  t80Reach: number | null;
  t95Reach: number | null;
};

type LaunchEvent = {
  id: string;
  tone: "info" | "success" | "error";
  text: string;
};

function toNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function mean(values: number[]): number | null {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}

function percentile(values: number[], pct: number): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  if (sorted.length === 1) return sorted[0];
  const rank = ((sorted.length - 1) * pct) / 100;
  const lower = Math.floor(rank);
  const upper = Math.ceil(rank);
  if (lower === upper) return sorted[lower];
  const weight = rank - lower;
  return sorted[lower] * (1 - weight) + sorted[upper] * weight;
}

function formatNumber(value: number | null | undefined, digits = 1, suffix = "") {
  if (value == null || !Number.isFinite(value)) return "--";
  return `${value.toFixed(digits)}${suffix}`;
}

function summarizeTrials(trials: ImportedTrial[]): SummaryRow[] {
  const byAlgorithm = new Map<string, ImportedTrial[]>();
  for (const trial of trials) {
    byAlgorithm.set(trial.algorithm, [...(byAlgorithm.get(trial.algorithm) ?? []), trial]);
  }

  return [...byAlgorithm.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([algorithm, rows]) => {
      const successes = rows.filter((row) => {
        const found = toNumber(row.targets_found) ?? 0;
        const total = toNumber(row.targets_total) ?? toNumber(row.target_count) ?? 0;
        return total > 0 && found >= total;
      }).length;
      const timeouts = rows.filter((row) => row.status === "timeout").length;
      const partials: number[] = [];
      const coverage: number[] = [];
      const firstFind: number[] = [];
      const overlap: number[] = [];
      const distancePerFind: number[] = [];
      const effortPerFind: number[] = [];
      const coveragePerDroneSecond: number[] = [];
      let missedHikers = 0;
      let t50 = 0;
      let t80 = 0;
      let t95 = 0;

      for (const row of rows) {
        const found = toNumber(row.targets_found) ?? 0;
        const total = toNumber(row.targets_total) ?? toNumber(row.target_count) ?? 0;
        if (total > 0) {
          partials.push((found / total) * 100);
          missedHikers += Math.max(total - found, 0);
        }
        const coverageValue = toNumber(row.coverage_pct);
        if (coverageValue != null) coverage.push(coverageValue);
        const first = toNumber(row.first_find_seconds);
        if (first != null) firstFind.push(first);
        const overlapValue = toNumber(row.redundant_coverage_pct);
        if (overlapValue != null) overlap.push(overlapValue);
        const distance = toNumber(row.total_distance_traveled_m);
        if (distance != null) distancePerFind.push(distance / Math.max(found, 1));
        const elapsed = toNumber(row.elapsed_seconds);
        const drones = toNumber(row.drone_count);
        if (elapsed != null && drones != null) effortPerFind.push((elapsed * drones) / Math.max(found, 1));
        const efficiency = toNumber(row.coverage_per_drone_second);
        if (efficiency != null) coveragePerDroneSecond.push(efficiency);
        if ((toNumber(row.time_to_50_coverage) ?? 0) > 0) t50 += 1;
        if ((toNumber(row.time_to_80_coverage) ?? 0) > 0) t80 += 1;
        if ((toNumber(row.time_to_95_coverage) ?? 0) > 0) t95 += 1;
      }

      return {
        algorithm,
        trials: rows.length,
        successRate: rows.length ? (successes / rows.length) * 100 : null,
        partialSuccess: mean(partials),
        timeoutRate: rows.length ? (timeouts / rows.length) * 100 : null,
        missedHikers,
        meanCoverage: mean(coverage),
        medianFirstFind: percentile(firstFind, 50),
        p90FirstFind: percentile(firstFind, 90),
        meanOverlap: mean(overlap),
        meanDistancePerFind: mean(distancePerFind),
        meanEffortPerFind: mean(effortPerFind),
        meanCoveragePerDroneSecond: mean(coveragePerDroneSecond),
        t50Reach: rows.length ? (t50 / rows.length) * 100 : null,
        t80Reach: rows.length ? (t80 / rows.length) * 100 : null,
        t95Reach: rows.length ? (t95 / rows.length) * 100 : null
      };
    });
}

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];
    if (quoted) {
      if (char === "\"" && next === "\"") {
        field += "\"";
        index += 1;
      } else if (char === "\"") {
        quoted = false;
      } else {
        field += char;
      }
    } else if (char === "\"") {
      quoted = true;
    } else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else if (char !== "\r") {
      field += char;
    }
  }
  row.push(field);
  if (row.some((value) => value.length > 0)) rows.push(row);
  return rows;
}

function trialFromCsvRow(headers: string[], row: string[], source: string): ImportedTrial | null {
  const raw: Record<string, string> = {};
  headers.forEach((header, index) => {
    raw[header] = row[index] ?? "";
  });
  if (!raw.algorithm || !raw.run_id) return null;
  const numberFields = [
    "id",
    "iteration",
    "scenario_seed",
    "drone_count",
    "target_count",
    "timeout_seconds",
    "elapsed_seconds",
    "first_find_seconds",
    "avg_find_seconds",
    "last_find_seconds",
    "completion_elapsed_seconds",
    "coverage_pct",
    "miss_pct",
    "redundant_coverage_pct",
    "coverage_per_drone_second",
    "hiker_find_rate",
    "total_distance_traveled_m",
    "avg_distance_per_drone_m",
    "max_distance_single_drone_m",
    "time_to_50_coverage",
    "time_to_80_coverage",
    "time_to_95_coverage",
    "targets_found",
    "targets_total"
  ];
  const trial: Record<string, unknown> = { ...raw, source };
  for (const field of numberFields) {
    if (field in raw) trial[field] = toNumber(raw[field]);
  }
  if (raw.bounds_json) {
    try {
      trial.bounds = JSON.parse(raw.bounds_json);
    } catch {
      trial.bounds = undefined;
    }
  }
  return trial as ImportedTrial;
}

function makeCsv(rows: ImportedTrial[], summary: SummaryRow[]) {
  const trialCsv = [
    TRIAL_EXPORT_FIELDS.join(","),
    ...rows.map((row) => TRIAL_EXPORT_FIELDS.map((field) => csvEscape(String((row as Record<string, unknown>)[field] ?? ""))).join(","))
  ].join("\n");
  const summaryFields: Array<keyof SummaryRow> = [
    "algorithm",
    "trials",
    "successRate",
    "partialSuccess",
    "timeoutRate",
    "missedHikers",
    "meanCoverage",
    "medianFirstFind",
    "p90FirstFind",
    "meanOverlap",
    "meanDistancePerFind",
    "meanEffortPerFind",
    "meanCoveragePerDroneSecond",
    "t50Reach",
    "t80Reach",
    "t95Reach"
  ];
  const summaryCsv = [
    summaryFields.join(","),
    ...summary.map((row) => summaryFields.map((field) => csvEscape(String(row[field] ?? ""))).join(","))
  ].join("\n");
  return { trialCsv, summaryCsv };
}

function csvEscape(value: string) {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, "\"\"")}"` : value;
}

function downloadText(filename: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function downloadSvg(svgId: string, filename: string) {
  const svg = document.getElementById(svgId);
  if (!svg) return;
  downloadText(filename, new XMLSerializer().serializeToString(svg), "image/svg+xml");
}

function BarChart({
  id,
  title,
  data,
  suffix = "",
  digits = 1
}: {
  id: string;
  title: string;
  data: { label: string; value: number | null }[];
  suffix?: string;
  digits?: number;
}) {
  const width = 720;
  const height = 260;
  const maxValue = Math.max(...data.map((item) => item.value ?? 0), 1);
  const barWidth = data.length ? 520 / data.length : 520;
  return (
    <div className="metrics-chart-panel">
      <div className="metrics-chart-header">
        <h3>{title}</h3>
        <button type="button" onClick={() => downloadSvg(id, `${id}.svg`)} disabled={!data.length}>SVG</button>
      </div>
      {data.length ? (
        <svg id={id} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
          <line x1="110" y1="22" x2="110" y2="210" className="chart-axis" />
          <line x1="110" y1="210" x2="680" y2="210" className="chart-axis" />
          {data.map((item, index) => {
            const value = item.value ?? 0;
            const barHeight = (value / maxValue) * 150;
            const x = 128 + index * barWidth;
            const y = 210 - barHeight;
            return (
              <g key={item.label}>
                <rect x={x} y={y} width={Math.max(barWidth - 18, 18)} height={barHeight} rx="4" className="chart-bar" />
                <text x={x + Math.max(barWidth - 18, 18) / 2} y={y - 8} textAnchor="middle" className="chart-value">
                  {formatNumber(item.value, digits, suffix)}
                </text>
                <text x={x + Math.max(barWidth - 18, 18) / 2} y="232" textAnchor="middle" className="chart-label">
                  {item.label}
                </text>
              </g>
            );
          })}
        </svg>
      ) : (
        <div className="metrics-chart-empty">Waiting for completed trial rows.</div>
      )}
    </div>
  );
}

function ScatterChart({ id, trials }: { id: string; trials: ImportedTrial[] }) {
  const width = 720;
  const height = 260;
  const algorithms = [...new Set(trials.map((trial) => trial.algorithm))].sort();
  return (
    <div className="metrics-chart-panel">
      <div className="metrics-chart-header">
        <h3>Coverage vs Hikers Found</h3>
        <button type="button" onClick={() => downloadSvg(id, `${id}.svg`)} disabled={!trials.length}>SVG</button>
      </div>
      {trials.length ? (
        <svg id={id} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Coverage versus hikers found">
          <line x1="70" y1="210" x2="680" y2="210" className="chart-axis" />
          <line x1="70" y1="30" x2="70" y2="210" className="chart-axis" />
          <text x="375" y="246" textAnchor="middle" className="chart-label">coverage percent</text>
          <text x="18" y="122" textAnchor="middle" className="chart-label" transform="rotate(-90 18 122)">hikers found percent</text>
          {trials.map((trial, index) => {
            const coverage = toNumber(trial.coverage_pct) ?? 0;
            const found = toNumber(trial.targets_found) ?? 0;
            const total = toNumber(trial.targets_total) ?? toNumber(trial.target_count) ?? 1;
            const x = 70 + (coverage / 100) * 610;
            const y = 210 - (found / Math.max(total, 1)) * 180;
            const classIndex = algorithms.indexOf(trial.algorithm) % 7;
            return <circle key={`${trial.run_id}-${trial.algorithm}-${trial.iteration}-${index}`} cx={x} cy={y} r="4" className={`chart-dot dot-${classIndex}`} />;
          })}
        </svg>
      ) : (
        <div className="metrics-chart-empty">Scatter points appear after trial rows are written.</div>
      )}
    </div>
  );
}

function FindTimeChart({ id, summary }: { id: string; summary: SummaryRow[] }) {
  const width = 720;
  const height = Math.max(170, 58 + summary.length * 36);
  const maxValue = Math.max(...summary.map((row) => row.p90FirstFind ?? row.medianFirstFind ?? 0), 1);
  return (
    <div className="metrics-chart-panel">
      <div className="metrics-chart-header">
        <h3>First-Find Distribution</h3>
        <button type="button" onClick={() => downloadSvg(id, `${id}.svg`)} disabled={!summary.length}>SVG</button>
      </div>
      {summary.length ? (
        <svg id={id} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="First find distribution">
          <line x1="140" y1={height - 34} x2="680" y2={height - 34} className="chart-axis" />
          {summary.map((row, index) => {
            const y = 38 + index * 36;
            const median = row.medianFirstFind ?? 0;
            const p90 = row.p90FirstFind ?? median;
            const medianX = 140 + (median / maxValue) * 520;
            const p90X = 140 + (p90 / maxValue) * 520;
            return (
              <g key={row.algorithm}>
                <text x="128" y={y + 4} textAnchor="end" className="chart-label">{row.algorithm}</text>
                <line x1="140" y1={y} x2={p90X} y2={y} className="chart-range" />
                <circle cx={medianX} cy={y} r="5" className="chart-bar" />
                <text x={Math.min(p90X + 8, 660)} y={y + 4} className="chart-value">
                  p50 {formatSeconds(median)} / p90 {formatSeconds(p90)}
                </text>
              </g>
            );
          })}
        </svg>
      ) : (
        <div className="metrics-chart-empty">First-find distribution appears after at least one hiker is found.</div>
      )}
    </div>
  );
}

export default function MetricsPage() {
  const apiPort = getApiPort();
  const apiBase = useMemo(() => getApiBase(apiPort), [apiPort]);
  const client = useMemo(() => createMissionClient(apiBase), [apiBase]);
  const [algorithmOptions, setAlgorithmOptions] = useState<AlgorithmMetadata[]>(DEFAULT_ALGORITHM_OPTIONS);
  const [scenarioProfiles, setScenarioProfiles] = useState<BenchmarkScenarioProfile[]>(DEFAULT_SCENARIO_PROFILES);
  const [selectedAlgorithms, setSelectedAlgorithms] = useState<Record<string, boolean>>({});
  const [selectedScenarios, setSelectedScenarios] = useState<Record<string, boolean>>({ uniform_random: true });
  const [preset, setPreset] = useState("6km");
  const [bounds, setBounds] = useState<Bounds>(BOUNDS_PRESETS["6km"].bounds);
  const [iterations, setIterations] = useState(50);
  const [droneCount, setDroneCount] = useState(15);
  const [targetCount, setTargetCount] = useState(3);
  const [timeoutSeconds, setTimeoutSeconds] = useState(BOUNDS_PRESETS["6km"].timeout);
  const [seed, setSeed] = useState("42");
  const [runs, setRuns] = useState<BenchmarkRun[]>([]);
  const [loadedRuns, setLoadedRuns] = useState<Record<string, BenchmarkRun>>({});
  const [selectedRunIds, setSelectedRunIds] = useState<Record<string, boolean>>({});
  const [activeRunIds, setActiveRunIds] = useState<string[]>([]);
  const [importedTrials, setImportedTrials] = useState<ImportedTrial[]>([]);
  const [progressMessage, setProgressMessage] = useState<BenchmarkProgressMessage | null>(null);
  const [loading, setLoading] = useState(false);
  const [launchStatus, setLaunchStatus] = useState<string | null>(null);
  const [launchLog, setLaunchLog] = useState<LaunchEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [lastPollAt, setLastPollAt] = useState<Date | null>(null);
  const onSocketConnected = useCallback((_connected: boolean) => undefined, []);
  const onSocketMessage = useCallback((_message: unknown) => undefined, []);

  useMissionSocket({
    apiPort,
    onConnectedChange: onSocketConnected,
    onTelemetry: onSocketMessage,
    onMissionStatus: onSocketMessage,
    onMissionProgress: onSocketMessage,
    onTargetFound: onSocketMessage,
    onBenchmarkProgress: setProgressMessage
  });

  const selectedScenarioKeys = useMemo(
    () => scenarioProfiles.filter((profile) => selectedScenarios[profile.key]).map((profile) => profile.key),
    [scenarioProfiles, selectedScenarios]
  );
  const selectedAlgorithmKeys = useMemo(
    () => algorithmOptions.filter((option) => selectedAlgorithms[option.key]).map((option) => option.key),
    [algorithmOptions, selectedAlgorithms]
  );
  const selectedRunIdList = useMemo(
    () => Object.keys(selectedRunIds).filter((id) => selectedRunIds[id]),
    [selectedRunIds]
  );

  useEffect(() => {
    client.listAlgorithms()
      .then((payload) => {
        const next = payload.algorithms.length ? payload.algorithms : DEFAULT_ALGORITHM_OPTIONS;
        setAlgorithmOptions(next);
        setSelectedAlgorithms((current) => {
          const updated: Record<string, boolean> = {};
          for (const option of next) updated[option.key] = current[option.key] ?? ["pmv", "sweep", "pso", "vaco"].includes(option.key);
          return updated;
        });
      })
      .catch(() => undefined);
    client.listBenchmarkScenarios()
      .then((payload) => setScenarioProfiles(payload.scenarios.length ? payload.scenarios : DEFAULT_SCENARIO_PROFILES))
      .catch(() => undefined);
    client.listBenchmarkRuns()
      .then((payload) => setRuns(payload.runs))
      .catch(() => undefined);
  }, [client]);

  const refreshRun = useCallback(async (runId: string) => {
    const run = await client.getBenchmarkRun(runId);
    setLoadedRuns((current) => ({ ...current, [runId]: run }));
    setLastPollAt(new Date());
    return run;
  }, [client]);

  useEffect(() => {
    const ids = [...new Set([...selectedRunIdList, ...activeRunIds])];
    ids.forEach((runId) => {
      refreshRun(runId).catch(() => undefined);
    });
  }, [activeRunIds, refreshRun, selectedRunIdList]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      client.listBenchmarkRuns()
        .then((payload) => {
          setRuns(payload.runs);
          const runningIds = payload.runs
            .filter((run) => run.status === "running")
            .map((run) => run.run_id);
          if (runningIds.length) {
            setActiveRunIds((current) => [...new Set([...current, ...runningIds])]);
          }
        })
        .catch(() => undefined);

      const idsToPoll = [...new Set([...selectedRunIdList, ...activeRunIds])];
      idsToPoll.forEach((runId) => {
        refreshRun(runId).then((run) => {
          if (run.status !== "running") {
            setActiveRunIds((current) => current.filter((id) => id !== runId));
          }
        }).catch(() => undefined);
      });
    }, 1500);
    return () => window.clearInterval(interval);
  }, [activeRunIds, client, refreshRun, selectedRunIdList]);

  useEffect(() => {
    if (!progressMessage?.run_id) return;
    refreshRun(progressMessage.run_id).catch(() => undefined);
  }, [progressMessage, refreshRun]);

  const displayedRunIds = useMemo(
    () => [...new Set([...selectedRunIdList, ...activeRunIds])],
    [activeRunIds, selectedRunIdList]
  );
  const databaseTrials = useMemo(
    () => displayedRunIds.flatMap((runId) => loadedRuns[runId]?.trials ?? []).map((trial) => ({ ...trial, source: "database" })),
    [displayedRunIds, loadedRuns]
  );
  const allTrials = useMemo(() => [...databaseTrials, ...importedTrials], [databaseTrials, importedTrials]);
  const summary = useMemo(() => summarizeTrials(allTrials), [allTrials]);
  const completedTrials = displayedRunIds.reduce((total, runId) => total + (loadedRuns[runId]?.completed_trials ?? 0), 0);
  const totalTrials = displayedRunIds.reduce((total, runId) => total + (loadedRuns[runId]?.total_trials ?? 0), 0);
  const progressPct = totalTrials > 0 ? (completedTrials / totalTrials) * 100 : 0;
  const { trialCsv, summaryCsv } = useMemo(() => makeCsv(allTrials, summary), [allTrials, summary]);
  const monitoredRuns = useMemo(
    () => displayedRunIds.map((runId) => (
      loadedRuns[runId] ?? runs.find((run) => run.run_id === runId)
    )).filter((run): run is BenchmarkRun => Boolean(run)),
    [displayedRunIds, loadedRuns, runs]
  );

  const onPresetChange = useCallback((nextPreset: string) => {
    setPreset(nextPreset);
    const next = BOUNDS_PRESETS[nextPreset];
    if (!next) return;
    setBounds(next.bounds);
    setTimeoutSeconds(next.timeout);
  }, []);

  const onStartRuns = useCallback(async () => {
    if (!selectedAlgorithmKeys.length || !selectedScenarioKeys.length) return;
    setLoading(true);
    setLaunchStatus(`Preparing ${selectedScenarioKeys.length} scenario run${selectedScenarioKeys.length === 1 ? "" : "s"}`);
    setLaunchLog([]);
    setError(null);
    try {
      const started: string[] = [];
      for (const [index, scenario] of selectedScenarioKeys.entries()) {
        setLaunchStatus(`Starting ${scenario} (${index + 1}/${selectedScenarioKeys.length})`);
        setLaunchLog((current) => [
          {
            id: `${Date.now()}-${scenario}-request`,
            tone: "info",
            text: `Requesting ${scenario} with ${selectedAlgorithmKeys.length} algorithms x ${iterations} iterations.`
          },
          ...current
        ]);
        const run = await client.startBenchmark({
          algorithms: selectedAlgorithmKeys,
          iterations,
          bounds,
          drone_count: droneCount,
          target_count: targetCount,
          timeout_seconds: timeoutSeconds,
          scenario_profile: scenario,
          seed: seed ? Number(seed) : undefined
        });
        started.push(run.run_id);
        setLoadedRuns((current) => ({ ...current, [run.run_id]: run }));
        setActiveRunIds((current) => [...new Set([...current, run.run_id])]);
        setSelectedRunIds((current) => ({ ...current, [run.run_id]: true }));
        setLaunchLog((current) => [
          {
            id: `${Date.now()}-${run.run_id}-created`,
            tone: "success",
            text: `Started ${run.run_id} for ${scenario}. Progress polling is active.`
          },
          ...current
        ]);
      }
      setLaunchStatus(`Running ${started.length} Metrics run${started.length === 1 ? "" : "s"}`);
      client.listBenchmarkRuns().then((payload) => setRuns(payload.runs)).catch(() => undefined);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Could not start Metrics runs";
      setError(message);
      setLaunchStatus("Launch failed");
      setLaunchLog((current) => [{ id: `${Date.now()}-error`, tone: "error", text: message }, ...current]);
    } finally {
      setLoading(false);
    }
  }, [bounds, client, droneCount, iterations, seed, selectedAlgorithmKeys, selectedScenarioKeys, targetCount, timeoutSeconds]);

  const onImportCsv = useCallback(async (files: FileList | null) => {
    if (!files?.length) return;
    const imported: ImportedTrial[] = [];
    for (const file of Array.from(files)) {
      const text = await file.text();
      const rows = parseCsv(text);
      const headers = rows[0] ?? [];
      for (const row of rows.slice(1)) {
        const trial = trialFromCsvRow(headers, row, file.name);
        if (trial) imported.push(trial);
      }
    }
    setImportedTrials((current) => [...current, ...imported]);
  }, []);

  const singleSelectedRunId = displayedRunIds.length === 1 ? displayedRunIds[0] : null;

  return (
    <div className="control-page metrics-page">
      <TopBar title="Metrics" showProgress={false} />
      <main className="metrics-layout">
        <section className="metrics-hero">
          <div>
            <p className="metrics-eyebrow">SAR benchmark workspace</p>
            <h2>Run paired scenario metrics and inspect live trial data.</h2>
          </div>
          <div className="metrics-live-status">
            <span>{loading ? "Launching" : activeRunIds.length ? "Running" : "Ready"}</span>
            <strong>{completedTrials}/{totalTrials || allTrials.length}</strong>
            <div className="progress-bar">
              <div className="progress-fill" style={{ width: `${Math.min(progressPct, 100)}%` }} />
            </div>
            <small>{lastPollAt ? `Polled ${lastPollAt.toLocaleTimeString()}` : "Polling every 1.5s"}</small>
          </div>
        </section>

        <section className="metrics-grid">
          <div className="metrics-panel metrics-setup">
            <div className="metrics-panel-header">
              <h3>Run Setup</h3>
              <button type="button" onClick={onStartRuns} disabled={loading || !selectedAlgorithmKeys.length || !selectedScenarioKeys.length}>
                {loading ? "Launching Runs" : "Run Metrics"}
              </button>
            </div>

            <div className="metrics-subgrid">
              <label className="field">
                Bounds preset
                <select value={preset} onChange={(event) => onPresetChange(event.target.value)}>
                  {Object.entries(BOUNDS_PRESETS).map(([key, item]) => <option key={key} value={key}>{item.label}</option>)}
                </select>
              </label>
              <label className="field">
                Iterations
                <input type="number" min={1} max={500} value={iterations} onChange={(event) => setIterations(Number(event.target.value))} />
              </label>
              <label className="field">
                Drones
                <input type="number" min={1} max={50} value={droneCount} onChange={(event) => setDroneCount(Number(event.target.value))} />
              </label>
              <label className="field">
                Hikers
                <input type="number" min={1} max={20} value={targetCount} onChange={(event) => setTargetCount(Number(event.target.value))} />
              </label>
              <label className="field">
                Timeout seconds
                <input type="number" min={1} max={3600} value={timeoutSeconds} onChange={(event) => setTimeoutSeconds(Number(event.target.value))} />
              </label>
              <label className="field">
                Seed
                <input value={seed} onChange={(event) => setSeed(event.target.value.replace(/[^\d]/g, ""))} />
              </label>
            </div>

            <div className="metrics-bounds-grid">
              {(["min_lat", "max_lat", "min_lon", "max_lon"] as const).map((key) => (
                <label className="field" key={key}>
                  {key}
                  <input
                    type="number"
                    step="0.0001"
                    value={bounds[key]}
                    onChange={(event) => setBounds((current) => ({ ...current, [key]: Number(event.target.value) }))}
                  />
                </label>
              ))}
            </div>

            <div className="metrics-picker-block">
              <div className="metrics-picker-title">
                <span>Algorithms</span>
                <strong>{selectedAlgorithmKeys.length} selected</strong>
              </div>
              <div className="metrics-check-grid" aria-label="Metrics algorithms">
                {algorithmOptions.map((option) => (
                  <label key={option.key} className="benchmark-check">
                    <input
                      type="checkbox"
                      checked={selectedAlgorithms[option.key] ?? false}
                      onChange={(event) => setSelectedAlgorithms((current) => ({ ...current, [option.key]: event.target.checked }))}
                    />
                    <span>{option.label}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="metrics-picker-block">
              <div className="metrics-picker-title">
                <span>Scenarios</span>
                <strong>{selectedScenarioKeys.length} selected</strong>
              </div>
              <div className="metrics-check-grid scenarios" aria-label="Metrics scenarios">
                {scenarioProfiles.map((profile) => (
                  <label key={profile.key} className="benchmark-check">
                    <input
                      type="checkbox"
                      checked={selectedScenarios[profile.key] ?? false}
                      onChange={(event) => setSelectedScenarios((current) => ({ ...current, [profile.key]: event.target.checked }))}
                    />
                    <span>{profile.label}{profile.targets_move ? " (moving)" : " (stationary)"}</span>
                  </label>
                ))}
              </div>
            </div>
            <div className="metrics-launch-status" aria-live="polite">
              <strong>{launchStatus ?? "No run active"}</strong>
              <span>
                {selectedScenarioKeys.length} scenario{selectedScenarioKeys.length === 1 ? "" : "s"} x {selectedAlgorithmKeys.length} algorithm{selectedAlgorithmKeys.length === 1 ? "" : "s"} x {iterations} iteration{iterations === 1 ? "" : "s"}
              </span>
            </div>
            {launchLog.length > 0 && (
              <div className="metrics-launch-log" aria-label="Metrics launch log">
                {launchLog.slice(0, 5).map((event) => (
                  <div key={event.id} className={`metrics-launch-event ${event.tone}`}>{event.text}</div>
                ))}
              </div>
            )}
            {error && <div className="error-text">{error}</div>}
          </div>

          <div className="metrics-panel">
            <div className="metrics-panel-header">
              <h3>Database and CSV</h3>
              <label className="metrics-import">
                Import CSV
                <input type="file" accept=".csv,text/csv" multiple onChange={(event) => onImportCsv(event.target.files)} />
              </label>
            </div>
            <div className="metrics-run-list" aria-label="Database Metrics runs">
              {runs.map((run) => (
                <label key={run.run_id} className="metrics-run-row">
                  <input
                    type="checkbox"
                    checked={selectedRunIds[run.run_id] ?? false}
                    onChange={(event) => setSelectedRunIds((current) => ({ ...current, [run.run_id]: event.target.checked }))}
                  />
                  <span>
                    <strong>{run.run_id}</strong>
                    {run.status} | {run.request?.scenario_profile ?? "uniform_random"} | {run.completed_trials}/{run.total_trials}
                  </span>
                </label>
              ))}
            </div>
            <div className="benchmark-export-row">
              <button type="button" className="benchmark-export" onClick={() => downloadText("metrics_trials.csv", trialCsv, "text/csv")} disabled={!allTrials.length}>Export Combined CSV</button>
              <button type="button" className="benchmark-export" onClick={() => downloadText("metrics_summary.csv", summaryCsv, "text/csv")} disabled={!summary.length}>Export Summary CSV</button>
              {singleSelectedRunId && (
                <>
                  <a className="benchmark-export" href={`${apiBase}/benchmark/export?run_id=${encodeURIComponent(singleSelectedRunId)}`}>Raw Run CSV</a>
                  <a className="benchmark-export" href={`${apiBase}/benchmark/${encodeURIComponent(singleSelectedRunId)}/report.csv`}>Run Summary CSV</a>
                  <a className="benchmark-export" href={`${apiBase}/benchmark/${encodeURIComponent(singleSelectedRunId)}/report.md`}>Report MD</a>
                </>
              )}
            </div>
          </div>
        </section>

        {monitoredRuns.length > 0 && (
          <section className="metrics-panel">
            <div className="metrics-panel-header"><h3>Run Monitor</h3></div>
            <div className="metrics-monitor-grid">
              {monitoredRuns.map((run) => {
                const wsCompleted = progressMessage?.run_id === run.run_id ? progressMessage.completed : undefined;
                const wsTotal = progressMessage?.run_id === run.run_id ? progressMessage.total : undefined;
                const completed = wsCompleted ?? run.completed_trials ?? 0;
                const total = wsTotal ?? run.total_trials ?? 0;
                const pct = total > 0 ? Math.min((completed / total) * 100, 100) : 0;
                return (
                  <div key={run.run_id} className="metrics-monitor-row">
                    <div>
                      <strong>{run.run_id}</strong>
                      <span>{run.request?.scenario_profile ?? "uniform_random"} | {run.status}</span>
                    </div>
                    <div className="metrics-monitor-progress">
                      <span>{completed}/{total}</span>
                      <div className="progress-bar">
                        <div className="progress-fill" style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
            {allTrials.length === 0 && (
              <div className="hint-text">Runs are active. Charts appear as soon as the first completed trial row is persisted.</div>
            )}
          </section>
        )}

        <section className="metrics-scorecards">
          <div><span>Trials</span><strong>{allTrials.length}</strong></div>
          <div><span>Algorithms</span><strong>{summary.length}</strong></div>
          <div><span>Scenarios</span><strong>{new Set(allTrials.map((trial) => trial.scenario_profile ?? "uniform_random")).size}</strong></div>
          <div><span>Imported rows</span><strong>{importedTrials.length}</strong></div>
        </section>

        <section className="metrics-notes">
          <p>May 2026 fixed-600s 6/10/12 km runs showed PMV success at 80.0%, 43.9%, and 39.3%. The 10/12 km drop is dominated by time budget; use iso-effort comparisons before making scale claims.</p>
          <p>Current live charts update from completed trial rows. Per-tick coverage curves and cumulative per-hiker find curves need the planned benchmark snapshot table before they can be exact.</p>
        </section>

        <section className="metrics-charts">
          <BarChart id="metrics-success-rate" title="Success Rate" suffix="%" data={summary.map((row) => ({ label: row.algorithm, value: row.successRate }))} />
          <BarChart id="metrics-coverage" title="Mean Coverage" suffix="%" data={summary.map((row) => ({ label: row.algorithm, value: row.meanCoverage }))} />
          <BarChart id="metrics-effort" title="Drone Seconds per Find" data={summary.map((row) => ({ label: row.algorithm, value: row.meanEffortPerFind }))} digits={0} />
          <FindTimeChart id="metrics-find-time" summary={summary} />
          <ScatterChart id="metrics-coverage-scatter" trials={allTrials} />
        </section>

        <section className="metrics-panel">
          <div className="metrics-panel-header"><h3>Algorithm Summary</h3></div>
          {summary.length > 0 ? (
            <div className="benchmark-table-wrap">
              <table className="benchmark-table metrics-summary-table">
                <thead>
                  <tr>
                    <th>Algorithm</th>
                    <th>Trials</th>
                    <th>Success</th>
                    <th>Partial</th>
                    <th>Timeout</th>
                    <th>Missed</th>
                    <th>Median First</th>
                    <th>P90 First</th>
                    <th>Coverage</th>
                    <th>Overlap</th>
                    <th>T80 Reach</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.map((row) => (
                    <tr key={row.algorithm}>
                      <th>{row.algorithm}</th>
                      <td>{row.trials}</td>
                      <td>{formatNumber(row.successRate, 1, "%")}</td>
                      <td>{formatNumber(row.partialSuccess, 1, "%")}</td>
                      <td>{formatNumber(row.timeoutRate, 1, "%")}</td>
                      <td>{row.missedHikers}</td>
                      <td>{row.medianFirstFind == null ? "--" : formatSeconds(row.medianFirstFind)}</td>
                      <td>{row.p90FirstFind == null ? "--" : formatSeconds(row.p90FirstFind)}</td>
                      <td>{formatNumber(row.meanCoverage, 1, "%")}</td>
                      <td>{formatNumber(row.meanOverlap, 1, "%")}</td>
                      <td>{formatNumber(row.t80Reach, 1, "%")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="metrics-chart-empty">Select a database run, import CSVs, or wait for a running benchmark to finish its first trial.</div>
          )}
        </section>
      </main>
    </div>
  );
}
