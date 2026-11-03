"use client";

import { useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight, X } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { RepoList } from "@/components/repos/RepoList";
import { JobList } from "@/components/jobs/JobList";
import { MappingRail } from "@/components/mapping/MappingRail";

export function LeftRail() {
  const ws = useWorkspace();
  const open = ws.railDrawerOpen;
  const railClass = `rail${open ? " is-open" : ""}`;

  return (
    <>
      <aside className={railClass} aria-label="Repositories, jobs and mappings">
        <div className="drawer-head">
          <span className="label">Panels</span>
          <button type="button" className="icon-btn" aria-label="Close panels" onClick={() => ws.setRailDrawerOpen(false)}>
            <X className="icon" aria-hidden="true" />
          </button>
        </div>
        <div className="rail-scroll">
          <Section title="Repositories" count={ws.repoList.length}>
            <RepoList />
          </Section>
          <Section title="Jobs" count={ws.jobList.length}>
            <JobList />
          </Section>
          <Section
            title="Mappings"
            count={ws.symbols.data ? ws.symbols.data.symbols.filter((item) => !item.resolved).length : undefined}
            amber
          >
            <MappingRail />
          </Section>
        </div>
      </aside>
    </>
  );
}

interface SectionProps {
  title: string;
  count?: number;
  amber?: boolean;
  children: ReactNode;
}

function Section({ title, count, amber = false, children }: SectionProps) {
  const [collapsed, setCollapsed] = useState(false);
  const Chevron = collapsed ? ChevronRight : ChevronDown;
  return (
    <section className="section" aria-label={title}>
      <button
        type="button"
        className="section-head"
        aria-expanded={!collapsed}
        onClick={() => setCollapsed((value) => !value)}
      >
        <Chevron className="icon" aria-hidden="true" />
        <span className="section-title">{title}</span>
        {count !== undefined && count > 0 ? <span className={`count${amber ? " amber" : ""}`}>{count}</span> : null}
      </button>
      {collapsed ? null : children}
    </section>
  );
}
