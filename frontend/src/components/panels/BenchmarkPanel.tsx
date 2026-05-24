import { useCallback, useEffect, useMemo, useState } from "react";
import { createMissionClient } from "../../api/missionClient";
import type {
  AlgorithmOption,
  AlgorithmMetadata,
  BenchmarkMetricStats,
  BenchmarkRun,
  BenchmarkScenarioProfile,
  Bounds
} from "../../types/mission";
import type { BenchmarkProgressMessage } from "../../types/ws";
import CollapsibleSection from "../common/CollapsibleSection";

const METRICS: { key: string; label: string; suffix?: string }[] = [
  { key: "first_find_seconds", label: "First Find", suffix: "s" },
  { key: "avg_find_seconds", label: "Avg Find", suffix: "s" },
  { key: "coverage_pct", label: "Coverage", suffix: "%" },
  { key: "redundant_coverage_pct", label: "Overlap", suffix: "%" },
  { key: "coverage_per_drone_second", label: "Cov/Drone/s" }
];

const DEFAULT_SCENARIO_PROFILES: BenchmarkScenarioProfile[] = [
  {
    key: "uniform_random",
    label: "Uniform Random",
    description: "Stationary baseline with independent random drone and hiker placement.",
    targets_move: false
  }
];

type BenchmarkPanelProps = {
  apiBase: string;
  selectedBounds: Bounds | null;
  validDroneCount: number;
  progressMessage: BenchmarkProgressMessage | null;
  algorithmOptions: AlgorithmMetadata[];
};

function metricStats(value: unknown): BenchmarkMetricStats | null {
  if (!value || typeof value !== "object") return null;
  const stats = value as Partial<BenchmarkMetricStats>;
  return {
    mean: typeof stats.mean === "number" ? stats.mean : null,
    min: typeof stats.min === "number" ? stats.min : null,
    max: typeof stats.max === "number" ? stats.max : null,
    stddev: typeof stats.stddev === "number" ? stats.stddev : null
  };
}

function formatMetric(stats: BenchmarkMetricStats | null, suffix = "") {
  if (!stats || stats.mean == null) return "--";
  const spread = stats.stddev != null ? ` +/- ${stats.stddev.toFixed(1)}` : "";
  return `${stats.mean.toFixed(stats.mean < 1 ? 3 : 1)}${spread}${suffix}`;
}

function scenarioLabel(profileKey: string | undefined, profiles: BenchmarkScenarioProfile[]) {
  if (!profileKey) return "Uniform Random";
  return profiles.find((profile) => profile.key === profileKey)?.label ?? profileKey;
}

export default function BenchmarkPanel({
  apiBase,
  selectedBounds,
  validDroneCount,
  progressMessage,
  algorithmOptions
}: BenchmarkPanelProps) {
  const client = useMemo(() => createMissionClient(apiBase), [apiBase]);
  const [selectedAlgorithms, setSelectedAlgorithms] = useState<Record<AlgorithmOption, boolean>>({});
  const [iterations, setIterations] = useState(50);
  const [targetCount, setTargetCount] = useState(3);
  const [timeoutSeconds, setTimeoutSeconds] = useState(120);
  const [scenarioProfile, setScenarioProfile] = useState("uniform_random");
  const [scenarioProfiles, setScenarioProfiles] = useState<BenchmarkScenarioProfile[]>(DEFAULT_SCENARIO_PROFILES);
  const [run, setRun] = useState<BenchmarkRun | null>(null);
  const [runs, setRuns] = useState<BenchmarkRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const algorithms = useMemo(
    () => algorithmOptions.filter((option) => selectedAlgorithms[option.key]).map((option) => option.key),
    [algorithmOptions, selectedAlgorithms]
  );
  const activeRunId = run?.run_id ?? null;
  const isRunning = run?.status === "running";
  const completed = progressMessage?.run_id === activeRunId ? progressMessage.completed ?? run?.completed_trials ?? 0 : run?.completed_trials ?? 0;
  const total = progressMessage?.run_id === activeRunId ? progressMessage.total ?? run?.total_trials ?? 0 : run?.total_trials ?? 0;
  const progressPct = total > 0 ? Math.round((completed / total) * 100) : 0;
  const activeScenarioProfile = run?.request?.scenario_profile ?? scenarioProfile;

  const refreshRun = useCallback(
    async (runId: string) => {
      const nextRun = await client.getBenchmarkRun(runId);
      setRun(nextRun);
      return nextRun;
    },
    [client]
  );

  const loadRuns = useCallback(async () => {
    const payload = await client.listBenchmarkRuns();
    setRuns(payload.runs);
    return payload.runs;
  }, [client]);

  const loadScenarioProfiles = useCallback(async () => {
    const payload = await client.listBenchmarkScenarios();
    setScenarioProfiles(payload.scenarios.length ? payload.scenarios : DEFAULT_SCENARIO_PROFILES);
    setScenarioProfile((current) => (
      payload.scenarios.some((profile) => profile.key === current)
        ? current
        : payload.scenarios[0]?.key ?? "uniform_random"
    ));
  }, [client]);

  useEffect(() => {
    loadRuns().catch(() => {
      setRuns([]);
    });
    loadScenarioProfiles().catch(() => {
      setScenarioProfiles(DEFAULT_SCENARIO_PROFILES);
    });
  }, [loadRuns, loadScenarioProfiles]);

  useEffect(() => {
    setSelectedAlgorithms((prev) => {
      const next: Record<AlgorithmOption, boolean> = {};
      for (const option of algorithmOptions) {
        next[option.key] = prev[option.key] ?? true;
      }
      return next;
    });
  }, [algorithmOptions]);

  useEffect(() => {
    if (!activeRunId || !isRunning) return;
    const interval = window.setInterval(() => {
      refreshRun(activeRunId).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(interval);
  }, [activeRunId, isRunning, refreshRun]);

  useEffect(() => {
    if (!progressMessage?.run_id || progressMessage.run_id !== activeRunId) return;
    if (
      progressMessage.status === "complete" ||
      progressMessage.status === "failed" ||
      progressMessage.status === "cancelled"
    ) {
      refreshRun(progressMessage.run_id).then(() => loadRuns()).catch(() => undefined);
    }
  }, [activeRunId, loadRuns, progressMessage, refreshRun]);

  const onStart = useCallback(async () => {
    if (!selectedBounds || !algorithms.length) return;
    setLoading(true);
    setError(null);
    try {
      const nextRun = await client.startBenchmark({
        algorithms,
        iterations,
        bounds: selectedBounds,
        drone_count: Math.max(validDroneCount, 1),
        target_count: targetCount,
        timeout_seconds: timeoutSeconds,
        scenario_profile: scenarioProfile
      });
      setRun(nextRun);
      await loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Metrics failed");
    } finally {
      setLoading(false);
    }
  }, [algorithms, client, iterations, loadRuns, scenarioProfile, selectedBounds, targetCount, timeoutSeconds, validDroneCount]);

  const onStop = useCallback(async () => {
    if (!activeRunId || !isRunning) return;
    setStopping(true);
    setError(null);
    try {
      await client.stopBenchmark(activeRunId);
      await refreshRun(activeRunId);
      await loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not stop metrics run");
    } finally {
      setStopping(false);
    }
  }, [activeRunId, client, isRunning, loadRuns, refreshRun]);

  const onSelectRun = useCallback(
    async (runId: string) => {
      if (!runId) {
        setRun(null);
        return;
      }
      setError(null);
      try {
        await refreshRun(runId);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load metrics run");
      }
    },
    [refreshRun]
  );

  const summary = run?.summary ?? {};

  return (
    <CollapsibleSection title="Metrics" defaultOpen={false}>
      <div className="benchmark-stack">
        <div className="benchmark-checks" aria-label="Metrics algorithms">
          {algorithmOptions.map((option) => (
            <label key={option.key} className="benchmark-check">
              <input
                type="checkbox"
                checked={selectedAlgorithms[option.key] ?? true}
                onChange={(event) =>
                  setSelectedAlgorithms((prev) => ({ ...prev, [option.key]: event.target.checked }))
                }
                disabled={isRunning}
              />
              <span>{option.label}</span>
            </label>
          ))}
        </div>

        <div className="benchmark-input-grid">
          <label className="field">
            Scenario
            <select
              className="algorithm-select"
              value={scenarioProfile}
              onChange={(event) => setScenarioProfile(event.target.value)}
              disabled={isRunning}
            >
              {scenarioProfiles.map((profile) => (
                <option key={profile.key} value={profile.key}>
                  {profile.label}{profile.targets_move ? " (moving)" : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Iterations
            <input
              type="number"
              min={1}
              max={500}
              value={iterations}
              onChange={(event) => setIterations(Number(event.target.value))}
              disabled={isRunning}
            />
          </label>
          <label className="field">
            Targets
            <input
              type="number"
              min={1}
              max={20}
              value={targetCount}
              onChange={(event) => setTargetCount(Number(event.target.value))}
              disabled={isRunning}
            />
          </label>
          <label className="field">
            Timeout (seconds)
            <input
              type="number"
              min={1}
              max={3600}
              value={timeoutSeconds}
              onChange={(event) => setTimeoutSeconds(Number(event.target.value))}
              disabled={isRunning}
              aria-label="Timeout per trial in seconds"
            />
          </label>
          <label className="field">
            Drones
            <input type="number" value={Math.max(validDroneCount, 1)} readOnly />
          </label>
        </div>

        <div className="benchmark-actions">
          <button
            type="button"
            className="action-btn start"
            onClick={onStart}
            disabled={!selectedBounds || !algorithms.length || loading || isRunning}
          >
            {isRunning ? "Metrics Running" : "Run Metrics"}
          </button>
          <button
            type="button"
            className="action-btn stop"
            onClick={onStop}
            disabled={!activeRunId || !isRunning || stopping}
          >
            {stopping ? "Stopping…" : "Stop Metrics"}
          </button>
        </div>

        {!selectedBounds && <div className="hint-text warning-text">Set a search area before running metrics.</div>}
        {error && <div className="error-text">{error}</div>}

        {run && (
          <div className="benchmark-progress-block">
            <div className="benchmark-progress-row">
              <span>{run.status}</span>
              <strong>{completed}/{total}</strong>
            </div>
            <div className="hint-text">
              Scenario: {scenarioLabel(activeScenarioProfile, scenarioProfiles)}
            </div>
            <div className="progress-bar benchmark-progress">
              <div className="progress-fill" style={{ width: `${progressPct}%` }} />
            </div>
          </div>
        )}

        {runs.length > 0 && (
          <label className="field">
            Metrics History
            <select
              className="algorithm-select"
              value={run?.run_id ?? ""}
              onChange={(event) => onSelectRun(event.target.value)}
            >
              <option value="">Latest runs</option>
              {runs.map((item) => (
                <option key={item.run_id} value={item.run_id}>
                  {item.run_id} ({item.status}, {scenarioLabel(item.request?.scenario_profile, scenarioProfiles)})
                </option>
              ))}
            </select>
          </label>
        )}

        {Object.keys(summary).length > 0 && (
          <div className="benchmark-table-wrap">
            <table className="benchmark-table">
              <thead>
                <tr>
                  <th>Algorithm</th>
                  {METRICS.map((metric) => (
                    <th key={metric.key}>{metric.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(summary).map(([algorithm, metrics]) => (
                  <tr key={algorithm}>
                    <th>{algorithm}</th>
                    {METRICS.map((metric) => (
                      <td key={metric.key}>
                        {formatMetric(metricStats(metrics[metric.key]), metric.suffix)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {run?.run_id && (
          <div className="benchmark-export-row">
            <a
              className="benchmark-export"
              href={`${apiBase}/benchmark/export?run_id=${encodeURIComponent(run.run_id)}`}
            >
              Export Metrics CSV
            </a>
            <a
              className="benchmark-export"
              href={`${apiBase}/benchmark/${encodeURIComponent(run.run_id)}/report.md`}
            >
              Export Report Markdown
            </a>
          </div>
        )}
      </div>
    </CollapsibleSection>
  );
}
