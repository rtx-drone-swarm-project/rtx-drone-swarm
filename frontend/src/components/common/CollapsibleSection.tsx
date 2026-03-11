import { useState, type ReactNode } from "react";

type CollapsibleSectionProps = {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
};

export default function CollapsibleSection({
  title,
  children,
  defaultOpen = true
}: CollapsibleSectionProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <section className="section-card">
      <button
        type="button"
        className="section-toggle"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
      >
        <span>{title}</span>
        <span className="section-chevron">{open ? "▴" : "▾"}</span>
      </button>
      {open && <div className="section-body">{children}</div>}
    </section>
  );
}
