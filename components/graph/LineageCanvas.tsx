"use client";

import "@xyflow/react/dist/style.css";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  applyNodeChanges,
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
import { ConstellationSimulation, constellationSeeds } from "@/lib/constellation";
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
/** Lowest zoom at which the first view still shows the whole graph rather than its entry nodes. */
const WHOLE_GRAPH_ZOOM = 0.4;
const CAMERA_MS = 420;

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
  view?: "flow" | "constellation";
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

/** A topology change starts a fresh simulation and discards obsolete node measurements. */
export function LineageCanvas(props: LineageCanvasProps) {
  const signature = useMemo(() => JSON.stringify([
    props.view,
    props.nodes.map((node) => node.id).sort(),
    props.edges.map((edge) => [edge.id, edge.source, edge.target]).sort(),
  ]), [props.view, props.nodes, props.edges]);
  return <GraphCanvas key={signature} {...props} signature={signature} />;
}

function GraphCanvas(props: LineageCanvasProps & { signature: string }) {
  const { nodes, edges, roles, unresolvedIds, selection, onNavigateNode, signature } = props;
  const constellation = props.view === "constellation";
  const [initialPositions] = useState(() => constellation ? constellationSeeds(nodes) : layeredLayout(nodes, edges));
  // Keep every React Flow change, including measured dimensions and dragging.
  // Highlight and selection decorate these objects without replacing geometry.
  const [controlledNodes, setControlledNodes] = useState<LineageFlowNode[]>(() => nodes.map((node) => ({
    id: node.id,
    type: "lineage",
    position: initialPositions.get(node.id) ?? { x: 0, y: 0 },
    width: NODE_WIDTH,
    height: constellation ? 152 : NODE_HEIGHT,
    data: { node, role: null, path: null, unresolved: false, selected: false, constellation, enterDelay: 0 },
  })));
  const [simulation] = useState(() => constellation ? new ConstellationSimulation(nodes, edges) : null);
  const [hasPinnedNodes, setHasPinnedNodes] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const frame = useRef<number | null>(null);
  const mounted = useRef(false);
  const reducedMotion = useRef(false);

  const startSimulation = useCallback(() => {
    if (!simulation || frame.current !== null || !mounted.current) return;
    setSimulating(true);
    let lastFrame = 0;
    const advance = (time: number) => {
      if (!mounted.current) return;
      // Publish at most 30 times per second, leaving room for drag and zoom events.
      if (time - lastFrame < 32) {
        frame.current = window.requestAnimationFrame(advance);
        return;
      }
      lastFrame = time;
      let active = simulation.tick();
      if (reducedMotion.current) {
        for (let step = 1; step < 4 && active; step += 1) active = simulation.tick();
      }
      if (!reducedMotion.current || !active) {
        const nextPositions = simulation.positions();
        setControlledNodes((current) => current.map((node) => {
          const position = nextPositions.get(node.id);
          return position && !node.dragging ? { ...node, position } : node;
        }));
      }
      if (active) frame.current = window.requestAnimationFrame(advance);
      else {
        frame.current = null;
        setSimulating(false);
      }
    };
    frame.current = window.requestAnimationFrame(advance);
  }, [simulation]);

  useEffect(() => {
    mounted.current = true;
    reducedMotion.current = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    startSimulation();
    return () => {
      mounted.current = false;
      if (frame.current !== null) window.cancelAnimationFrame(frame.current);
      frame.current = null;
    };
  }, [startSimulation]);

  const onNodesChange = useCallback((changes: NodeChange<LineageFlowNode>[]) => {
    setControlledNodes((current) => applyNodeChanges(changes, current));
    for (const change of changes) {
      if (change.type !== "position" || !change.position) continue;
      setHasPinnedNodes(true);
      simulation?.pin(change.id, change.position);
    }
    if (changes.some((change) => change.type === "position" && change.position)) startSimulation();
  }, [simulation, startSimulation]);

  const resetLayout = useCallback(() => {
    simulation?.reset();
    setHasPinnedNodes(false);
    setControlledNodes((current) => current.map((node) => ({
      ...node,
      position: initialPositions.get(node.id) ?? node.position,
      dragging: false,
    })));
    startSimulation();
  }, [initialPositions, simulation, startSimulation]);

  const positions = useMemo(() => new Map(controlledNodes.map((node) => [node.id, node.position])), [controlledNodes]);
  const nodeIndex = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const entryIds = useMemo(() => {
    const targets = new Set(edges.map((edge) => edge.target));
    return nodes.filter((node) => !targets.has(node.id)).map((node) => node.id);
  }, [nodes, edges]);

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
      controlledNodes.map((geometry) => {
        const node = nodeIndex.get(geometry.id) ?? geometry.data.node;
        const position = geometry.position;
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
          ...geometry,
          selected,
          ariaLabel: `${kindName(node.kind)} ${node.name}`,
          data: {
            node,
            constellation,
            role: roles.get(node.id) ?? null,
            path: pathRole,
            unresolved: unresolvedIds.has(node.id),
            selected,
            enterDelay: constellation ? 0 : Math.min(ENTER_MAX, Math.round((position.x / (NODE_WIDTH + 72)) * ENTER_STEP)),
          },
        };
      }),
    [controlledNodes, nodeIndex, roles, unresolvedIds, selection, litId, litKind, hasLitNode, path, selectedEdge, constellation],
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
          data: { flow: onPath ? color : null, constellation },
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
    [edges, selection, hoveredEdge, hasLitNode, path, litId, litKind, selectedEdge, constellation],
  );

  // Arrow keys walk the graph: left/right follow edges, up/down move within the column.
  const graphRef = useRef({ nodes, edges, positions, selection, entryIds, onNavigateNode });
  useEffect(() => {
    graphRef.current = { nodes, edges, positions, selection, entryIds, onNavigateNode };
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
    <div className={`lineage-root${constellation ? " is-constellation" : ""}${entering ? " is-entering" : ""}`} role="group" aria-label={constellation ? "Entity constellation" : "Repository flow"}>
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
          positions={initialPositions}
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
        {constellation || hasPinnedNodes ? (
          <Panel position="bottom-center">
            {constellation ? <span className="simulation-status" role="status">{simulating ? "Settling…" : "Settled"}{hasPinnedNodes ? " · dragged nodes pinned" : " · drag to pin"}</span> : null}
            <button type="button" className="btn small canvas-action" onClick={resetLayout}>
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
    selection: Selection | null;
    entryIds: string[];
  },
): string | null {
  const { nodes, edges, positions, selection, entryIds } = graph;
  const at = (id: string) => positions.get(id) ?? { x: 0, y: 0 };
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

  const startX = (node.position.x + (node.measured?.width ?? NODE_WIDTH)) * zoom + tx;
  const startY = (node.position.y + (node.measured?.height ?? NODE_HEIGHT) / 2) * zoom + ty;
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
      if (overviewZoom >= WHOLE_GRAPH_ZOOM || entryIds.length === 0) {
        void fitView({ padding: padding(), duration: CAMERA_MS, maxZoom: 1.1, minZoom: WHOLE_GRAPH_ZOOM });
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
