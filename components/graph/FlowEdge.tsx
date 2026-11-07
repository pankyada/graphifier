"use client";

import { BaseEdge, getBezierPath, getSmoothStepPath, type Edge, type EdgeProps } from "@xyflow/react";

export type FlowEdgeType = Edge<{ flow: string | null; constellation?: boolean }, "flow">;

const PARTICLE_OFFSETS = [0, 0.9];

/** Smooth-step edge. On a lit lineage path, particles travel from source to target. */
export function FlowEdge(props: EdgeProps<FlowEdgeType>) {
  const pathBuilder = props.data?.constellation ? getBezierPath : getSmoothStepPath;
  const [path, labelX, labelY] = pathBuilder({
    sourceX: props.sourceX,
    sourceY: props.sourceY,
    targetX: props.targetX,
    targetY: props.targetY,
    sourcePosition: props.sourcePosition,
    targetPosition: props.targetPosition,
  });
  const flow = props.data?.flow ?? null;

  return (
    <>
      <BaseEdge
        id={props.id}
        path={path}
        style={props.style}
        markerEnd={props.markerEnd}
        interactionWidth={props.interactionWidth}
        label={props.label}
        labelX={labelX}
        labelY={labelY}
        labelStyle={props.labelStyle}
        labelBgStyle={props.labelBgStyle}
        labelBgPadding={props.labelBgPadding}
        labelBgBorderRadius={props.labelBgBorderRadius}
      />
      {flow
        ? PARTICLE_OFFSETS.map((offset) => (
            <g key={offset} className="edge-particle" aria-hidden="true">
              <circle r={6} fill={flow} opacity={0.18} />
              <circle r={2.75} fill={flow} />
              <animateMotion dur="1.8s" begin={`-${offset}s`} repeatCount="indefinite" path={path} />
            </g>
          ))
        : null}
    </>
  );
}
