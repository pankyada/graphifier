"use client";

import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { useWorkspace } from "@/components/workspace/WorkspaceContext";

interface ResizeHandleProps {
  target: "rail" | "inspector";
}

/** Drag or arrow-key resize for a side rail. Width is persisted by the workspace. */
export function ResizeHandle({ target }: ResizeHandleProps) {
  const ws = useWorkspace();
  const [dragging, setDragging] = useState(false);
  const startX = useRef(0);
  const startWidth = useRef(0);

  const width = target === "rail" ? ws.railWidth : ws.inspectorWidth;
  const setWidth = target === "rail" ? ws.setRailWidth : ws.setInspectorWidth;
  const hidden = target === "rail" ? ws.railHidden : ws.inspectorHidden;
  const label = target === "rail" ? "Resize repositories and jobs panel" : "Resize inspector panel";
  const sign = target === "rail" ? 1 : -1;

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    startX.current = event.clientX;
    startWidth.current = width;
    setDragging(true);
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    setWidth(startWidth.current + sign * (event.clientX - startX.current));
  };

  const onPointerUp = (event: PointerEvent<HTMLDivElement>) => {
    setDragging(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 32 : 8;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      setWidth(width - sign * step);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      setWidth(width + sign * step);
    }
  };

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={width}
      aria-hidden={hidden ? true : undefined}
      tabIndex={hidden ? -1 : 0}
      className={`handle handle-${target}${dragging ? " dragging" : ""}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onKeyDown={onKeyDown}
    />
  );
}
