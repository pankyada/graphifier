"use client";

import "@xyflow/react/dist/style.css";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  MiniMap,
  Panel,
  ReactFlow,
  useReactFlow,
  useStore,
  type Edge,
  type FitViewOptions,
  type NodeChange,
} from "@xyflow/react";
import { RotateCcw } from "lucide-react";
import { FlowEdge } from "./FlowEdge";
import { NodeCard, type LineageFlowNode, type LineageRole, type PathRole } from "./NodeCard";
import { kindColor, kindName } from "./kinds";
import { lineagePath, layeredLayout, NODE_HEIGHT, NODE_WIDTH, type Point } from "@/lib/layout";
import { setHighlight, useHighlight } from "@/lib/highlight";
import type { GraphEdge, GraphNode } from "@/lib/types";
import type { Selection } from "@/components/workspace/useWorkspace";

const nodeTypes = { lineage: NodeCard };
const edgeTypes = { flow: FlowEdge };

const EDGE_IDLE = "#8A8578";
const EDGE_SELECTED = "#1F6F5C";
const EDGE_UPSTREAM = "#1F6F5C";
const EDGE_DOWNSTREAM = "#B4532A";

/** Lowest zoom at which node names stay legible in the initial view. */
const READABLE_ZOOM = 0.6;
/** Lowest zoom the Fit overview and manual zoom-out may reach. */
const OVERVIEW_ZOOM = 0.1;
const CAMERA_MS = 420;

const NO_OVERRIDES = new Map<string, Point>();

const SHEET_MARGIN = 12;
/** Width of the inspector pull-tab, which the tether connects to. */
const TAB_WIDTH = 38;

/** Entrance wave: columns arrive left to right, following the direction of lineage. */
const ENTER_STEP = 55;
const ENTER_MAX = 550;
const ENTER_WINDOW = ENTER_MAX + 600;

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
  focusId: string | null;
  /** Width of the inspector sheet floating over the canvas; 0 when closed. */
  sheetWidth: number;
  fitNonce: number;
  onSelectNode: (id: string) => void;
  onNavigateNode: (id: string) => void;
  onFocusNode: (id: string) => void;
  onSelectEdge: (id: string) => void;
  onClearSelection: () => void;
}

/** Lineage canvas. Layout is a deterministic layered placement; the camera follows selection. */
export function LineageCanvas(props: LineageCanvasProps) {
  const { nodes, edges, roles, unresolvedIds, selection, onNavigateNode } = props;

  const positions = useMemo(() => layeredLayout(nodes, edges), [nodes, edges]);
  const signature = useMemo(() => nodes.map((node) => node.id).join("|"), [nodes]);
  // Nodes with no incoming edge start the lineage; the initial view anchors there when the whole graph is too large to read.
  const entryIds = useMemo(() => {
    const targets = new Set(edges.map((edge) => edge.target));
    return nodes.filter((node) => !targets.has(node.id)).map((node) => node.id);
  }, [nodes, edges]);

  // Dragged positions belong to the graph they were made in; a new node set starts from the layout again.
  const [dragged, setDragged] = useState<{ signature: string; points: Map<string, Point> } | null>(null);
  const overrides = dragged?.signature === signature ? dragged.points : NO_OVERRIDES;

  const onNodesChange = (changes: NodeChange<LineageFlowNode>[]) => {
    const moves = changes.filter((change) => change.type === "position" && change.position);
    if (moves.length === 0) return;
    const points = new Map(overrides);
    for (const change of moves) {
      if (change.type === "position" && change.position) points.set(change.id, change.position);
    }
    setDragged({ signature, points });
  };

  // Scoped to a short window so nodes panned into view later do not replay it.
  const [entering, setEntering] = useState(true);
  useEffect(() => {
    setEntering(true);
    const id = window.setTimeout(() => setEntering(false), ENTER_WINDOW);
    return () => window.clearTimeout(id);
  }, [signature]);

  const [hoveredEdge, setHoveredEdge] = useState<string | null>(null);
  const highlight = useHighlight();
  useEffect(() => () => setHighlight(null), []);

  // A hover previews; otherwise the selected node's lineage stays lit.
  // A hovered node can vanish under the pointer (trace, filter) without a mouseleave, so check it is still drawn.
  const hoverId = highlight?.type === "node" && nodes.some((node) => node.id === highlight.id) ? highlight.id : null;
  const litKind = highlight?.type === "kind" ? highlight.kind : null;
  const litId = hoverId ?? (!litKind && selection?.kind === "node" ? selection.id : null);

  const path = useMemo(() => (litId ? lineagePath(litId, edges) : null), [litId, edges]);
  // A node with no lineage has nothing to light up, so the rest of the graph stays readable.
  const hasLitNode =
    !!litId && !!path && path.upstream.size + path.downstream.size > 0 && nodes.some((node) => node.id === litId);
  const selectedEdge = selection?.kind === "edge" ? edges.find((edge) => edge.id === selection.id) : undefined;

  const flowNodes = useMemo<LineageFlowNode[]>(
    () =>
      nodes.map((node) => {
        const position = overrides.get(node.id) ?? positions.get(node.id) ?? { x: 0, y: 0 };
        const selected = selection?.kind === "node" && selection.id === node.id;
        let pathRole: PathRole = null;
        if (litKind) pathRole = node.kind === litKind ? null : "dim";
        else if (hasLitNode && path) {
          if (node.id === litId) pathRole = "self";
          else if (path.upstream.has(node.id)) pathRole = "upstream";
          else if (path.downstream.has(node.id)) pathRole = "downstream";
          else pathRole = "dim";
        } else if (selectedEdge && node.id !== selectedEdge.source && node.id !== selectedEdge.target) {
          pathRole = "dim";
        }
        return {
          id: node.id,
          type: "lineage",
          position,
          width: NODE_WIDTH,
          height: NODE_HEIGHT,
          selected,
          ariaLabel: `${kindName(node.kind)} ${node.name}`,
          data: {
            node,
            role: roles.get(node.id) ?? null,
            path: pathRole,
            unresolved: unresolvedIds.has(node.id),
            selected,
            enterDelay: Math.min(ENTER_MAX, Math.round((position.x / (NODE_WIDTH + 72)) * ENTER_STEP)),
          },
        };
      }),
    [nodes, positions, overrides, roles, unresolvedIds, selection, litId, litKind, hasLitNode, path, selectedEdge],
  );

  const tetherNode = selection?.kind === "node" ? flowNodes.find((node) => node.id === selection.id) : undefined;
  const tetherColor = tetherNode ? kindColor(tetherNode.data.node.kind) : EDGE_IDLE;

  const flowEdges = useMemo<Edge[]>(
    () =>
      edges.map((edge) => {
        const selected = selection?.kind === "edge" && selection.id === edge.id;
        const hovered = hoveredEdge === edge.id;
        const onPath = hasLitNode && !!path && (path.upstreamEdges.has(edge.id) || path.downstreamEdges.has(edge.id));
        const direct = onPath && (edge.source === litId || edge.target === litId);
        let color = EDGE_IDLE;
        if (selected || hovered) color = EDGE_SELECTED;
        else if (onPath && path) color = path.upstreamEdges.has(edge.id) ? EDGE_UPSTREAM : EDGE_DOWNSTREAM;
        const dimmed =
          !selected &&
          !hovered &&
          (litKind !== null || (hasLitNode && !onPath) || (!!selectedEdge && selectedEdge.id !== edge.id));
        const showLabel = selected || hovered || direct;
        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          type: "flow",
          selected,
          data: { flow: onPath ? color : null },
          interactionWidth: 16,
          label: showLabel ? edge.kind.replace(/_/g, " ").toLowerCase() : undefined,
          labelStyle: { fontSize: 10, fontWeight: 500, fill: color },
          labelBgStyle: { fill: "#fff", stroke: "#E5E2DB", strokeWidth: 1 },
          labelBgPadding: [5, 2] as [number, number],
          labelBgBorderRadius: 4,
          markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color },
          style: {
            stroke: color,
            strokeWidth: selected || hovered || onPath ? 2.25 : 1.5,
            strokeDasharray: edge.kind === "RESOLVES_TO" ? "5 4" : undefined,
            opacity: dimmed ? 0.14 : 1,
            transition: "opacity 120ms ease, stroke 120ms ease",
          },
        };
      }),
    [edges, selection, hoveredEdge, hasLitNode, path, litId, litKind, selectedEdge],
  );

  // Arrow keys walk the graph: left/right follow edges, up/down move within the column.
  const graphRef = useRef({ nodes, edges, positions, overrides, selection, entryIds, onNavigateNode });
  useEffect(() => {
    graphRef.current = { nodes, edges, positions, overrides, selection, entryIds, onNavigateNode };
  });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
      if (event.metaKey || event.ctrlKey || event.altKey || document.querySelector("dialog[open]")) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
      if (target?.closest(".inspector, .rail, [role='slider'], [role='separator']")) return;
      const graph = graphRef.current;
      const next = nextNode(event.key, graph);
      // Capture phase: stops React Flow from also nudging a keyboard-focused node.
      event.preventDefault();
      event.stopPropagation();
      if (next) graph.onNavigateNode(next);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);

  return (
    <div className={`lineage-root${entering ? " is-entering" : ""}`} role="group" aria-label="Lineage graph">
      <ReactFlow
        nodes={flowNodes}
        edges={flowEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        minZoom={0.1}
        maxZoom={2}
        nodesConnectable={false}
        deleteKeyCode={null}
        zoomOnDoubleClick={false}
        onlyRenderVisibleElements
        onNodesChange={onNodesChange}
        onNodeClick={(_, node) => props.onSelectNode(node.id)}
        onNodeDoubleClick={(_, node) => {
          setHighlight(null);
          props.onFocusNode(node.id);
        }}
        onNodeMouseEnter={(_, node) => setHighlight({ type: "node", id: node.id })}
        onNodeMouseLeave={() => setHighlight(null)}
        onEdgeClick={(_, edge) => props.onSelectEdge(edge.id)}
        onEdgeMouseEnter={(_, edge) => setHoveredEdge(edge.id)}
        onEdgeMouseLeave={() => setHoveredEdge(null)}
        onPaneClick={props.onClearSelection}
      >
        <Camera
          positions={positions}
          entryIds={entryIds}
          signature={signature}
          fitNonce={props.fitNonce}
          centerRequest={props.centerRequest}
          focusId={props.focusId}
          sheetWidth={props.sheetWidth}
          selectedId={selection?.kind === "node" ? selection.id : null}
        />
        <Tether
          node={tetherNode}
          color={tetherColor}
          tabRight={props.sheetWidth > 0 ? props.sheetWidth + SHEET_MARGIN : 0}
        />
        <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#DAD6CD" />
        <Controls position="bottom-right" showInteractive={false} />
        <MiniMap
          position="bottom-left"
          pannable
          zoomable
          maskColor="rgba(247, 246, 243, 0.7)"
          nodeColor={(node) => {
            const data = (node as LineageFlowNode).data;
            if (node.selected) return EDGE_SELECTED;
            return data?.node ? `${kindColor(data.node.kind)}80` : "#D2CEC4";
          }}
          nodeStrokeWidth={2}
          style={{ width: 150, height: 96 }}
          ariaLabel="Graph minimap"
        />
        {overrides.size > 0 ? (
          <Panel position="bottom-center">
            <button type="button" className="btn small canvas-action" onClick={() => setDragged(null)}>
              <RotateCcw className="icon" aria-hidden="true" />
              Reset layout
            </button>
          </Panel>
        ) : null}
      </ReactFlow>
    </div>
  );
}

function nextNode(
  key: string,
  graph: {
    nodes: GraphNode[];
    edges: GraphEdge[];
    positions: Map<string, Point>;
    overrides: Map<string, Point>;
    selection: Selection | null;
    entryIds: string[];
  },
): string | null {
  const { nodes, edges, positions, overrides, selection, entryIds } = graph;
  const at = (id: string) => overrides.get(id) ?? positions.get(id) ?? { x: 0, y: 0 };
  const current = selection?.kind === "node" && nodes.some((node) => node.id === selection.id) ? selection.id : null;
  if (!current) return entryIds[0] ?? nodes[0]?.id ?? null;
  const origin = at(current);

  // Candidates are ranked nearest first, so a key press lands on what the eye expects.
  const nearest = (ids: string[]) =>
    ids.sort((a, b) => Math.abs(at(a).y - origin.y) - Math.abs(at(b).y - origin.y) || a.localeCompare(b))[0] ?? null;

  if (key === "ArrowLeft") return nearest(edges.filter((edge) => edge.target === current).map((edge) => edge.source));
  if (key === "ArrowRight") return nearest(edges.filter((edge) => edge.source === current).map((edge) => edge.target));

  const sign = key === "ArrowUp" ? -1 : 1;
  const column = nodes
    .map((node) => node.id)
    .filter((id) => id !== current && Math.abs(at(id).x - origin.x) < NODE_WIDTH / 2)
    .filter((id) => (at(id).y - origin.y) * sign > 0);
  return nearest(column);
}

interface CameraProps {
  positions: Map<string, Point>;
  entryIds: string[];
  signature: string;
  fitNonce: number;
  centerRequest: { id: string; nonce: number } | null;
  focusId: string | null;
  sheetWidth: number;
  selectedId: string | null;
}

/** Live line from the selected node to the inspector tab, tying what is read to where it sits. */
function Tether({ node, color, tabRight }: { node: LineageFlowNode | undefined; color: string; tabRight: number }) {
  const [tx, ty, zoom] = useStore((state) => state.transform);
  const width = useStore((state) => state.width);
  const height = useStore((state) => state.height);
  if (!node || width === 0) return null;

  const startX = (node.position.x + NODE_WIDTH) * zoom + tx;
  const startY = (node.position.y + NODE_HEIGHT / 2) * zoom + ty;
  const endX = width - tabRight - TAB_WIDTH;
  const endY = height / 2;
  // Off-screen or already beside the tab: a line there would only add noise.
  const visibleY = startY > 0 && startY < height;
  if (startX < 0 || startX > endX - 24 || !visibleY) return null;

  const bend = Math.max(40, (endX - startX) / 2);
  const path = `M${startX} ${startY} C${startX + bend} ${startY} ${endX - bend} ${endY} ${endX} ${endY}`;
  return (
    <svg className="tether" aria-hidden="true">
      <path d={path} className="tether-line" style={{ stroke: color }} />
      <g className="edge-particle">
        <circle r={5} fill={color} opacity={0.2} />
        <circle r={2.5} fill={color} />
        <animateMotion dur="1.6s" repeatCount="indefinite" path={path} />
      </g>
    </svg>
  );
}

/**
 * Child of ReactFlow so it can use the viewport API. Renders nothing.
 *
 * Initial view (new graph or filter): the whole graph when it reads at or above
 * READABLE_ZOOM; otherwise the traced node, or without a trace the entry nodes, at
 * readable zoom, so text stays legible and the rest is reached by panning. The Fit button always shows the full overview.
 */
function Camera({ positions, entryIds, signature, fitNonce, centerRequest, focusId, sheetWidth, selectedId }: CameraProps) {
  const { fitView, setCenter, getZoom, getNode, getViewport, setViewport } = useReactFlow();
  const width = useStore((state) => state.width);
  const height = useStore((state) => state.height);

  const ready = width > 0 && height > 0;
  // Read through a ref: opening the sheet must not move the camera, only later moves account for it.
  const sheetRef = useRef(sheetWidth);
  sheetRef.current = sheetWidth;
  // Opening the sheet slides the camera just enough to keep the selected node beside it.
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;
  useEffect(() => {
    if (sheetWidth === 0 || !selectedRef.current) return;
    const point = getNode(selectedRef.current)?.position;
    if (!point) return;
    const viewport = getViewport();
    const right = (point.x + NODE_WIDTH) * viewport.zoom + viewport.x;
    const limit = width - sheetWidth - SHEET_MARGIN * 2 - TAB_WIDTH - 24;
    if (right <= limit) return;
    void setViewport({ ...viewport, x: viewport.x - (right - limit) }, { duration: CAMERA_MS });
    // Only opening or resizing the sheet should move the camera, never panning or selecting.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sheetWidth]);

  const padding = (): FitViewOptions["padding"] => ({
    top: "96px",
    bottom: "32px",
    left: "48px",
    right: `${sheetRef.current > 0 ? sheetRef.current + 72 : 72}px`,
  });

  useEffect(() => {
    const timer = window.setTimeout(() => {
      // A requested focus has its own centering effect below. Do not replace
      // that camera position with the graph's entry nodes after a trace loads.
      if (centerRequest && positions.has(centerRequest.id)) return;
      const bounds = graphBounds(positions);
      // Zoom at which the whole graph fits with 20% padding on each side.
      const overviewZoom = Math.min(((width - sheetRef.current) * 0.7) / bounds.width, (height * 0.6) / bounds.height);
      if (overviewZoom >= READABLE_ZOOM || entryIds.length === 0) {
        void fitView({ padding: padding(), duration: CAMERA_MS, maxZoom: 1.1, minZoom: READABLE_ZOOM });
        return;
      }
      const anchors = focusId && positions.has(focusId) ? [focusId] : entryIds;
      void fitView({
        nodes: anchors.map((id) => ({ id })),
        padding: padding(),
        duration: CAMERA_MS,
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
    void fitView({ padding: padding(), duration: CAMERA_MS, maxZoom: 1.1, minZoom: OVERVIEW_ZOOM });
  }, [fitNonce, fitView]);

  useEffect(() => {
    if (!centerRequest) return;
    // The live node position, so a dragged node is centered where it now sits.
    const point = getNode(centerRequest.id)?.position ?? positions.get(centerRequest.id);
    if (!point) return;
    const zoom = Math.max(getZoom(), 0.9);
    // Center in the area the sheet leaves free, not behind the sheet.
    void setCenter(point.x + NODE_WIDTH / 2 + sheetRef.current / 2 / zoom, point.y + NODE_HEIGHT / 2, {
      zoom,
      duration: CAMERA_MS,
    });
  }, [centerRequest, positions, setCenter, getZoom, getNode]);

  return null;
}
