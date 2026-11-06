"use client";

import { useEffect, useRef, useState } from "react";
import { Activity, FolderGit2, Link2, Pin, PinOff, type LucideIcon } from "lucide-react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";
import { RepoList } from "@/components/repos/RepoList";
import { JobList } from "@/components/jobs/JobList";
import { MappingRail } from "@/components/mapping/MappingRail";
import { isActive } from "@/lib/jobs";

type Section = "repos" | "jobs" | "mappings";

const SECTIONS: { id: Section; label: string; icon: LucideIcon }[] = [
  { id: "repos", label: "Repositories", icon: FolderGit2 },
  { id: "jobs", label: "Jobs", icon: Activity },
  { id: "mappings", label: "Mappings", icon: Link2 },
];

/** Pause before opening, so a pointer crossing the strip does not flash the panel. */
const OPEN_DELAY = 90;
/** Pause before closing, so a brief slip off the panel does not dismiss it. */
const CLOSE_DELAY = 260;

/**
 * Icon strip with a panel showing one section at a time. Unpinned, the panel opens
 * over the canvas on hover or click and collapses by itself once the pointer leaves
 * or the user acts. The pin at the bottom of the strip keeps it open.
 */
export function LeftRail() {
  const ws = useWorkspace();
  const [section, setSection] = useState<Section>("repos");
  const [peek, setPeek] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const root = useRef<HTMLElement>(null);

  const schedule = (open: boolean, next?: Section) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(
      () => {
        if (next) setSection(next);
        setPeek(open);
      },
      open ? OPEN_DELAY : CLOSE_DELAY,
    );
  };

  useEffect(() => () => window.clearTimeout(timer.current), []);

  // Choosing a repository or symbol, or opening a dialog, is the user moving on.
  useEffect(() => {
    window.clearTimeout(timer.current);
    setPeek(false);
  }, [ws.repoId, ws.scope, ws.dialog, ws.mappingSymbol, ws.mappingResolutionId]);

  useEffect(() => {
    if (!peek) return;
    const onPointer = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setPeek(false);
    };
    document.addEventListener("mousedown", onPointer);
    return () => document.removeEventListener("mousedown", onPointer);
  }, [peek]);

  const unresolved = ws.symbols.data?.symbols.filter((item) => !item.resolved).length ?? 0;
  const running = ws.jobList.some((job) => isActive(job));
  const current = SECTIONS.find((item) => item.id === section) ?? SECTIONS[0];
  const panelOpen = peek || ws.railPinned || ws.railDrawerOpen;

  const classes = ["rail", ws.railPinned ? "is-pinned" : "", peek ? "is-peek" : "", ws.railDrawerOpen ? "is-open" : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <aside
      ref={root}
      className={classes}
      aria-label="Repositories, jobs and mappings"
      onMouseLeave={() => schedule(false)}
      onMouseEnter={() => window.clearTimeout(timer.current)}
      onKeyDown={(event) => {
        if (event.key === "Escape" && peek) {
          event.stopPropagation();
          setPeek(false);
        }
      }}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) schedule(false);
      }}
    >
      <nav className="rail-strip" aria-label="Sidebar sections">
        {SECTIONS.map((item) => {
          const Icon = item.icon;
          const selected = panelOpen && section === item.id;
          return (
            <button
              key={item.id}
              type="button"
              className="rail-tab"
              aria-label={item.label}
              aria-current={selected ? "true" : undefined}
              data-tip={item.label}
              onMouseEnter={() => schedule(true, item.id)}
              onClick={() => {
                window.clearTimeout(timer.current);
                setSection(item.id);
                setPeek(true);
              }}
            >
              <Icon aria-hidden="true" />
              {item.id === "jobs" && running ? <span className="rail-pulse" aria-label="Analysis running" /> : null}
              {item.id === "mappings" && unresolved > 0 ? (
                <span className="rail-badge" aria-label={`${unresolved} unresolved`}>
                  {unresolved}
                </span>
              ) : null}
            </button>
          );
        })}
        <button
          type="button"
          className="rail-tab rail-pin"
          aria-label={ws.railPinned ? "Let sidebar collapse automatically" : "Keep sidebar open"}
          aria-pressed={ws.railPinned}
          data-tip={ws.railPinned ? "Collapse automatically" : "Keep open"}
          title={ws.railPinned ? "Let sidebar collapse automatically ([)" : "Keep sidebar open ([)"}
          onClick={() => {
            window.clearTimeout(timer.current);
            setPeek(false);
            ws.toggleRail();
          }}
        >
          {ws.railPinned ? <PinOff aria-hidden="true" /> : <Pin aria-hidden="true" />}
        </button>
      </nav>

      <div className="rail-panel" aria-hidden={!panelOpen}>
        <div className="rail-panel-head">{current.label}</div>
        {/* Keyed so that changing section replays the list entrance. */}
        <div className="rail-panel-body" key={section}>
          {section === "repos" ? <RepoList /> : null}
          {section === "jobs" ? <JobList /> : null}
          {section === "mappings" ? <MappingRail /> : null}
        </div>
      </div>
    </aside>
  );
}
