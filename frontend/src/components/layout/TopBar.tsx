type TopBarProps = {
  progress: number;
};

export default function TopBar({ progress }: TopBarProps) {
  const clampedProgress = Math.min(100, progress);

  return (
    <header className="topbar">
      <div className="title-group">
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
        <h1>Swarm Control</h1>
      </div>
      
      {/* Right side: Progress Group */}
      <div className="progress-group">
        <div className="progress-label">{clampedProgress.toFixed(1)}%</div>
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${clampedProgress}%` }} />
        </div>
      </div>
    </header>
  );
}
