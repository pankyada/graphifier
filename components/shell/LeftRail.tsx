"use client";

import { useState } from "react";
import { PanelLeftClose } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { ExplorePanel } from "@/components/graph/ExplorePanel";
import { JobList } from "@/components/jobs/JobList";
import { MappingRail } from "@/components/mapping/MappingRail";
import { isActive } from "@/lib/jobs";

type Section = "explore" | "jobs" | "mappings";

const SECTIONS: { id: Section; label: string }[] = [
  { id: "explore", label: "Explore" },
  { id: "jobs", label: "Jobs" },
  { id: "mappings", label: "Mappings" },
];

/** Left panel: entities to explore, analysis jobs, and symbol mappings. */
export function LeftRail() {
  const ws = useWorkspace();
  const [section, setSection] = useState<Section>("explore");

  const unresolved = ws.symbols.data?.symbols.filter((item) => !item.resolved).length ?? 0;
  const running = ws.jobList.some((job) => isActive(job));

  return (
    <aside className={`rail${ws.railDrawerOpen ? " is-open" : ""}`} aria-label="Explore, jobs and mappings">
      <div className="rail-tabs">
        <div role="tablist" aria-label="Sidebar sections" className="rail-tablist">
          {SECTIONS.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              className="rail-tab"
              aria-selected={section === item.id}
              onClick={() => setSection(item.id)}
            >
              {item.label}
              {item.id === "jobs" && running ? <span className="rail-running" aria-label="Analysis running" /> : null}
              {item.id === "mappings" && unresolved > 0 ? (
                <span className="rail-count" aria-label={`${unresolved} unresolved`}>
                  {unresolved}
                </span>
              ) : null}
            </button>
          ))}
        </div>
        <button type="button" className="icon-btn" aria-label="Hide sidebar" title="Hide sidebar ([)" onClick={ws.toggleRail}>
          <PanelLeftClose className="icon" aria-hidden="true" />
        </button>
      </div>
      <div className="rail-body" role="tabpanel">
        {section === "explore" ? <ExplorePanel /> : null}
        {section === "jobs" ? <JobList /> : null}
        {section === "mappings" ? <MappingRail /> : null}
      </div>
    </aside>
  );
}
