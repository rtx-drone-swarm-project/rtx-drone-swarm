type TopBarProps = {
  progress?: number;
  title?: string;
  showProgress?: boolean;
};

export default function TopBar({ progress = 0, title = "Swarm Control", showProgress = true }: TopBarProps) {
  const clampedProgress = Math.min(100, progress);

  return (
    <header className="topbar">
      <a className="title-group title-link" href="/" aria-label="Go to Swarm Control home">
        <svg 
          className="title-icon" 
          viewBox="0 0 24 24" 
          fill="none" 
          stroke="currentColor" 
          strokeWidth="2" 
          strokeLinecap="round" 
          strokeLinejoin="round"
        >
          {/* Center Body */}
          <rect x="10" y="10" width="4" height="4" rx="1" />
          
          {/* Top Left Arm & Propeller */}
          <path d="M10 10L6 6" />
          <path d="M3 6h6" />
          
          {/* Top Right Arm & Propeller */}
          <path d="M14 10l4-4" />
          <path d="M15 6h6" />
          
          {/* Bottom Left Arm & Propeller */}
          <path d="M10 14l-4 4" />
          <path d="M3 18h6" />
          
          {/* Bottom Right Arm & Propeller */}
          <path d="M14 14l4 4" />
          <path d="M15 18h6" />
        </svg>
        <h1>{title}</h1>
      </a>
      
      {showProgress ? (
        <div className="progress-group">
          <a className="topbar-pill-link" href="/metrics">Metrics</a>
          <div className="progress-label">{clampedProgress.toFixed(1)}%</div>
          <div className="progress-bar">
            <div className="progress-fill" style={{ width: `${clampedProgress}%` }} />
          </div>
        </div>
      ) : (
        <nav className="topbar-links" aria-label="Primary">
          <a href="/">Home</a>
        </nav>
      )}
    </header>
  );
}
