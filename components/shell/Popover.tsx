"use client";

import { useEffect, useRef, type ReactNode } from "react";

interface PopoverProps {
  /** Accessible name for the trigger. */
  label: string;
  trigger: ReactNode;
  triggerClassName?: string;
  align?: "left" | "right";
  width?: number;
  /** Receives `close` so that choosing an item can dismiss the popover. */
  children: (close: () => void) => ReactNode;
}

/** Top-bar dropdown built on details/summary. Closes on outside press and Escape. */
export function Popover({ label, trigger, triggerClassName, align = "left", width = 300, children }: PopoverProps) {
  const root = useRef<HTMLDetailsElement>(null);

  const close = () => {
    if (root.current) root.current.open = false;
  };

  useEffect(() => {
    const closeOutside = (event: PointerEvent) => {
      if (root.current && !root.current.contains(event.target as Node)) root.current.open = false;
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, []);

  return (
    <details
      ref={root}
      className="popover"
      onKeyDown={(event) => {
        if (event.key === "Escape" && root.current?.open) {
          event.stopPropagation();
          close();
          root.current.querySelector("summary")?.focus();
        }
      }}
    >
      <summary className={triggerClassName} aria-label={label}>
        {trigger}
      </summary>
      <div className={`popover-body ${align}`} style={{ width: `min(${width}px, calc(100vw - 24px))` }}>
        {children(close)}
      </div>
    </details>
  );
}
