type TopBarProps = {
  progress: number;
};

export default function TopBar({ progress }: TopBarProps) {
  const clampedProgress = Math.min(100, progress);

  return (
    <header className="topbar">
      <h1>Drone Swarm Control Panel</h1>
      <div className="progress-label">Search Progress: {clampedProgress.toFixed(1)}%</div>
      <div className="progress-bar">
        <div className="progress-fill" style={{ width: `${clampedProgress}%` }} />
      </div>
    </header>
  );
}
