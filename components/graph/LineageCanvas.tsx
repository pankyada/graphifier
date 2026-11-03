"use client";

import "@xyflow/react/dist/style.css";
import { useEffect, useMemo, useRef } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  useReactFlow,
  useStore,
  type Edge,
} from "@xyflow/react";
import { NodeCard, type LineageFlowNode, type LineageRole } from "./NodeCard";
import { kindName } from "./kinds";
import { layeredLayout, NODE_HEIGHT, NODE_WIDTH, type Point } from "@/lib/layout";
import type { GraphEdge, GraphNode } from "@/lib/types";
import type { Selection } from "@/components/workspace/useWorkspace";

const nodeTypes = { lineage: NodeCard };

const EDGE_IDLE = "#7A8394";
const EDGE_SELECTED = "#4F46E5";

/** Lowest zoom at which node names stay legible in the initial view. */
const READABLE_ZOOM = 0.6;
/** Lowest zoom the Fit overview and manual zoom-out may reach. */
const OVERVIEW_ZOOM = 0.1;

function graphBounds(positions: Map<string, Point>): { width: number; height: number } {
  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const point of positions.values()) {
    minX = Math.min(minX, point.x);
    minY = Math.min(minY, point.y);
    maxX = Math.max(maxX, point.x);
    maxY = Math.max(maxY, point.y);
  }
  if (!Number.isFinite(minX)) return { width: 1, height: 1 };
  return { width: maxX - minX + NODE_WIDTH, height: maxY - minY + NODE_HEIGHT };
}

export interface LineageCanvasProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  roles: Map<string, Exclude<LineageRole, null>>;
  unresolvedIds: Set<string>;
  selection: Selection | null;
  centerRequest: { id: string; nonce: number } | null;
  fitNonce: number;
  onSelectNode: (id: string) => void;
  onFocusNode: (id: string) => void;
  onSelectEdge: (id: string) => void;
  onClearSelection: () => void;
}

/** Lineage canvas. Layout is a deterministic layered placement; the camera follows selection. */
export function LineageCanvas(props: LineageCanvasProps) {
  const { nodes, edges, roles, unresolvedIds, selection } = props;

  const positions = useMemo(() => layeredLayout(nodes, edges), [nodes, edges]);
  const signature = useMemo(() => nodes.map((node) => node.id).join("|"), [nodes]);
  // Nodes with no incoming edge start the lineage; the initial view anchors there when the whole graph is too large to read.
  const entryIds = useMemo(() => {
    const targets = new Set(edges.map((edge) => edge.target));
    return nodes.filter((node) => !targets.has(node.id)).map((node) => node.id);
  }, [nodes, edges]);

  const flowNodes = useMemo<LineageFlowNode[]>(
    () =>
      nodes.map((node) => {
        const position = positions.get(node.id) ?? { x: 0, y: 0 };
        const selected = selection?.kind === "node" && selection.id === node.id;
        return {
          id: node.id,
          type: "lineage",
          position,
          width: NODE_WIDTH,
          height: NODE_HEIGHT,
          draggable: false,
          selected,
          ariaLabel: `${kindName(node.kind)} ${node.name}`,
          data: {
            node,
            role: roles.get(node.id) ?? null,
            unresolved: unresolvedIds.has(node.id),
            selected,
          },
        };
      }),
    [nodes, positions, roles, unresolvedIds, selection],
  );

  const flowEdges = useMemo<Edge[]>(
    () =>
      edges.map((edge) => {
        const selected = selection?.kind === "edge" && selection.id === edge.id;
        const color = selected ? EDGE_SELECTED : EDGE_IDLE;
        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          type: "smoothstep",
          selected,
          interactionWidth: 14,
          label: selected ? edge.kind.replace(/_/g, " ").toLowerCase() : undefined,
          markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color },
          style: {
            stroke: color,
            strokeWidth: selected ? 2 : 1.5,
            strokeDasharray: edge.kind === "RESOLVES_TO" ? "5 4" : undefined,
          },
        };
      }),
    [edges, selection],
  );

  return (
    <div className="lineage-root" role="group" aria-label="Lineage graph">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        minZoom={0.1}
        maxZoom={2}
        nodesDraggable={false}
        nodesConnectable={false}
        deleteKeyCode={null}
        onlyRenderVisibleElements
        onNodeClick={(_, node) => props.onSelectNode(node.id)}
        onNodeDoubleClick={(_, node) => props.onFocusNode(node.id)}
        onEdgeClick={(_, edge) => props.onSelectEdge(edge.id)}
        onPaneClick={props.onClearSelection}
      >
        <Camera
          positions={positions}
          entryIds={entryIds}
          signature={signature}
          fitNonce={props.fitNonce}
          centerRequest={props.centerRequest}
        />
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#D8DCE4" />
        <Controls position="bottom-right" showInteractive={false} />
        <MiniMap
          position="bottom-left"
          pannable
          zoomable
          maskColor="rgba(246, 247, 249, 0.7)"
          nodeColor={(node) => (node.selected ? EDGE_SELECTED : "#CBD0DA")}
          nodeStrokeWidth={2}
          style={{ width: 150, height: 96 }}
          ariaLabel="Graph minimap"
        />
      </ReactFlow>
    </div>
  );
}

interface CameraProps {
  positions: Map<string, Point>;
  entryIds: string[];
  signature: string;
  fitNonce: number;
  centerRequest: { id: string; nonce: number } | null;
}

/**
 * Child of ReactFlow so it can use the viewport API. Renders nothing.
 *
 * Initial view (new graph or filter): the whole graph when it reads at or above
 * READABLE_ZOOM; otherwise the entry nodes at readable zoom, so text stays legible
 * and the rest is reached by panning. The Fit button always shows the full overview.
 */
function Camera({ positions, entryIds, signature, fitNonce, centerRequest }: CameraProps) {
  const { fitView, setCenter, getZoom } = useReactFlow();
  const width = useStore((state) => state.width);
  const height = useStore((state) => state.height);

  const ready = width > 0 && height > 0;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      // A requested focus has its own centering effect below. Do not replace
      // that camera position with the graph's entry nodes after a trace loads.
      if (centerRequest && positions.has(centerRequest.id)) return;
      const bounds = graphBounds(positions);
      // Zoom at which the whole graph fits with 20% padding on each side.
      const overviewZoom = Math.min((width * 0.6) / bounds.width, (height * 0.6) / bounds.height);
      if (overviewZoom >= READABLE_ZOOM || entryIds.length === 0) {
        void fitView({ padding: 0.2, duration: 200, maxZoom: 1.1, minZoom: READABLE_ZOOM });
        return;
      }
      void fitView({
        nodes: entryIds.map((id) => ({ id })),
        padding: 0.2,
        duration: 200,
        maxZoom: 1.1,
        minZoom: READABLE_ZOOM,
      });
    }, 40);
    return () => window.clearTimeout(timer);
    // Resizing a panel must not reset the user's pan or zoom: width/height are read only when the graph changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, ready, positions, entryIds, fitView]);

  // Explicit overview: the Fit button bumps fitNonce. Remember the last handled value so
  // effect re-runs (React Strict Mode) do not replace the readable initial view.
  const handledFit = useRef(fitNonce);
  useEffect(() => {
    if (fitNonce === handledFit.current) return;
    handledFit.current = fitNonce;
    void fitView({ padding: 0.2, duration: 200, maxZoom: 1.1, minZoom: OVERVIEW_ZOOM });
  }, [fitNonce, fitView]);

  useEffect(() => {
    if (!centerRequest) return;
    const point = positions.get(centerRequest.id);
    if (!point) return;
    void setCenter(point.x + NODE_WIDTH / 2, point.y + NODE_HEIGHT / 2, {
      zoom: Math.max(getZoom(), 0.9),
      duration: 220,
    });
  }, [centerRequest, positions, setCenter, getZoom]);

  return null;
}
