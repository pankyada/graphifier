# Graphifier UI design (Next + @xyflow/react + lucide-react)

> Design direction from the approved Sonnet pass. The implementation follows the live API contract in `backend/API.md`. Integration updates supersede the original notes below: use relative `/api` through the existing Next.js server proxy; tokens stay server-side; jobs accept `environment`; Neo4j supports aggregate environment sync; evidence accepts `snapshot_id`; use local system fonts rather than remote downloads. No client-side token storage or force-cache control is required. Interaction details below are design targets; delivered scope is recorded in `IMPLEMENTATION.md`.

App = single-route workspace `/`. Light, flat, technical. No landing page, no hero, no marketing prose. API base `http://127.0.0.1:8787` via one typed `api.ts` client (env `NEXT_PUBLIC_API_BASE`). Errors shape `{detail}` -> show verbatim.

## 1. Tokens (CSS vars in globals.css; no gradients, no heavy shadows)

```
--bg:#F6F7F9  --panel:#FFFFFF  --sunken:#EEF0F4  --line:#E1E4EA  --line-strong:#CBD0DA
--ink:#171A21 --ink-2:#4A5262 --ink-3:#7A8394
--indigo-600:#4F46E5 (primary, selection, focus)  --indigo-50:#EEF0FF  --indigo-200:#C7CBFA
--teal-600:#0F9488 (resolved/ok/upstream)  --teal-50:#E6F6F4
--amber-600:#B7791F (unresolved/warning) --amber-50:#FDF5E4
--red-600:#C2410C (failed/conflict)  --red-50:#FDEEE7
--radius:6px (cards 8px)  --focus:0 0 0 2px #fff,0 0 0 4px var(--indigo-600)
```
Type: Inter (next/font) 13px base, 12px meta, 11px caps labels (letter-spacing .04em, ink-3). Mono (JetBrains Mono / ui-monospace) 12px for paths, ids, expressions, code. Max heading 15px/600. Spacing scale 4/8/12/16; row height 28px (dense), panel padding 12px, 1px borders instead of shadows. Icons: lucide 14-16px, stroke 1.75.

Status chips (11px, 20px high, tinted bg + 1px border, icon+text, never color alone): queued=ink-3, running=indigo (spinner), completed=teal, failed=red, cancelled=ink-3 strike. Unresolved = amber dashed. Resolved = teal.

## 2. Shell layout (CSS grid, 100vh, no page scroll)

```
[ TopBar 44px, full width ]
[ LeftRail 288px | Main (1fr) | Inspector 360px ]
[ StatusStrip 24px optional: API health, version ]
```
Rails resizable (drag handle, min 240/320, persisted localStorage); Inspector collapses to 0 with `]` key; below 1100px Inspector becomes overlay drawer, rail collapses to icon bar.

### TopBar
Left: wordmark "Graphifier" (15px/600, small indigo glyph, lucide `Waypoints`). Center-left: **Environment** combobox (free-text + recent values from localStorage; API has no env list; required for graph/symbols/propose; empty = prompt "Set environment" in Main, still allow aggregate graph w/o env if API accepts - send param only when set). **Scope** segmented: `Repo` / `All repos` (omit repo_id for aggregate). Search input (`/` focuses): client-side filter over loaded nodes by name/expression/kind (no search endpoint exists); results dropdown with kind icon + repo; Enter selects+centers. Right: `Sync Neo4j` button (disabled w/o repo; see 7), refresh icon, health dot (GET /api/health, poll 15s; red + "API unreachable" banner if fail), settings icon -> popover of GET /api/settings (read-only key/value, mono).

### LeftRail (three collapsible sections, 11px caps headers with counts)
1. **Repositories**: list rows (name 13px/500, path mono 11px ellipsized middle, active = indigo-50 bg + 2px indigo left bar). `+ Add` opens folder-browser dialog. Selecting sets repo scope.
2. **Jobs** (for selected repo, GET /api/jobs?repo_id): row = status chip, `processed/total` , 3px progress bar (indigo; completed teal), relative time, error line (red, 2-line clamp, expand). Running/queued rows show `Cancel` (icon button `X`, confirm-inline). Top of section: `Run analysis` button (opens dialog, 6).
3. **Mappings** (GET /api/resolutions): row = symbol mono, expression truncated, state chip (proposed/applied/retracted - render whatever string API returns), env tag. Click -> Inspector Mapping view. Sub-filter tabs: Unresolved | Mappings. Unresolved list comes from GET /api/symbols where `resolved=false`; amber count badge.

## 3. Main: Lineage Explorer

Toolbar above canvas (36px): focus chip ("Focus: customer_scores · dataset" with `x` clear), direction segmented `Upstream | Both | Downstream` (maps to trace direction in/both/out), kind filter multiselect (kinds from data, never hardcoded), `Fit`, `Layout` (LR dagre-like simple layered layout; implement own rank by BFS depth since no dagre installed, or add only if allowed), counts "N nodes · M edges" real counts only.

Canvas = ReactFlow, background `--bg` dotted grid #D8DCE4 gap 16, minimap bottom-left small, zoom controls restyled flat.

Loading: GET /api/graph?repo_id&environment. Large graph rule (DESIGN: never dump estate): if nodes > 150 and no focus, show list-first "Choose a focus" panel (searchable node list grouped by kind) instead of rendering all; show canvas on focus.

Focus flow: user picks node (search / click / list) -> GET /api/trace?entity_id&direction&repo_id&environment -> render only returned nodes/edges; focus node ringed indigo 2px; upstream nodes get teal 2px left stripe, downstream indigo-200 stripe. Dim non-trace nodes if showing full graph. Double-click node = refocus. Banner under toolbar: "Static analysis shows possible, not proven, runtime lineage" dismissible once (localStorage).

Node card (custom type, 200x56): kind icon (lucide by kind, fallback `Box`) + name (13px/500 ellipsis) ; sub-line mono 11px kind + evidence count (`FileCode2` n). Unresolved nodes: dashed amber border, amber-50 fill, `HelpCircle`. Selected: indigo border + focus ring. Edge: 1.5px ink-3 step/smooth; label = edge kind 10px on hover/selected only (avoid clutter); selected edge indigo 2px; arrow markers. Edges clickable (wide invisible hit path 12px).

## 4. Inspector (right, tabs, keyed by selection)

Header: kind chip + name + id (mono, copy button). Tabs: **Evidence** | **Details** | **Mapping** (Mapping only if node is unresolved/symbol).
- Evidence: list of `{file, start_line-end_line}` rows (mono, click to load). Selecting loads GET /api/evidence?repo_id&file -> code viewer: line numbers gutter, mono 12px, evidence range highlighted indigo-50 + left bar, auto-scrolled to start_line (use plain rows; virtualize if > 2000 lines). Footer shows `sha256` short (8 chars, copy) and caveat "Indexed snapshot, not working tree" (ink-3). For edge selection: header shows source -> target names + edge kind; evidence list as above.
- Details: attributes as key/value table (mono values), `expression` raw block labeled "Raw expression (never executed)".
- Mapping: see 5.

Empty inspector: "Select a node or edge to see indexed evidence." 12px ink-3 plus nothing else.

## 5. Unresolved symbols and bindings flow

Left rail Unresolved list -> click symbol -> Inspector Mapping tab with: symbol name, raw expression (mono), default_value, evidence list (same viewer), Environment (read-only, from TopBar; propose disabled if unset with hint). Form: `expression` (required, mono input), `default_value` (optional). Button `Propose` -> POST /api/resolutions/propose {repo_id,environment,symbol,expression,default_value,actor?}. Result card shows: state, expected version, **Preview of graph changes** (render whatever preview fields API returns as list: added/removed/changed nodes & edges, keep generic key-based renderer + raw JSON disclosure), **Conflicts** block red-50 listing existing live bindings on same repo/env/symbol (explicit conflict details; Apply disabled when conflicts present). Buttons: `Apply` (POST apply {expected_version}) primary indigo; `Refresh preview` (GET /preview); applied item shows `Retract` (red outline, inline confirm, POST retract {expected_version}). On 409/stale detail: show message + auto-refresh preview, require user to re-click. After apply/retract: refetch graph, symbols, resolutions; toast "Binding applied · graph reloaded". Optional actor field in settings popover (stored locally, sent as X-Graphifier-Actor + body actor).

## 6. Onboarding, folder browser, jobs

No repos yet: Main shows purposeful empty state, card 480px left-aligned (not centered hero): title "Register a repository" 15px, one 12px line "Pick a local folder. Graphifier reads files, never runs them." then 3-step compact checklist (1 Register folder, 2 Run analysis, 3 Explore lineage) with step state from real data. Primary button `Browse folders`. Secondary note: "Try with sample code: browse to the sample folders under your allowed root" - opens same folder browser (no baked-in fake repos, no metrics, no placeholder graph). Rail sections show terse empty rows ("None yet").

Folder browser dialog (560x480): breadcrumb (from path), list from GET /api/browse?path= (initial call without path gives allowlisted roots), folder rows with `Folder` icon, double-click/Enter descends, `..` up. Files hidden or greyed (is_dir false). Footer: name input (prefilled from folder basename), selected path mono, `Register` -> POST /api/repositories. Handle 4xx detail (outside allowlist, symlink) inline red. On success select repo, offer "Run analysis".

Run analysis dialog: radio cards. **Static analysis** (default, `Cpu`): "Parses locally. No data leaves this device." **Luna agent** (`Cloud`/`Send`): amber-50 disclosure "Sends bounded source excerpts to the configured OpenAI endpoint. Local storage does not mean local inference." Requires explicit checkbox "I understand source excerpts leave this device" before enabling Run. `Force re-index` checkbox (force). Never label static fallback as agent success: job row shows mode tag only from what was submitted (`static` / `agent`); if API returns error, show it. POST /api/jobs {repo_id,use_agent,force}. Note: API.md has no environment field on jobs; environment is a view parameter.

Polling: while any job queued/running poll GET /api/jobs?repo_id every 1500ms (backoff to 5s on error; stop when terminal; pause when tab hidden). On transition to completed -> refetch graph/symbols. Failed/cancelled: no graph reload claim; show chip + error, keep prior graph with note "Last completed snapshot" only if graph exists. Cancel -> POST cancel; chip shows "cancelling…" until polled status changes.

## 7. Neo4j sync and honest states

`Sync Neo4j` -> POST /api/neo4j/sync {repo_id}; button shows spinner; result popover: status, nodes, edges counts (real from response), or `error` in red. No sync-status GET exists: never show persistent "synced" badge; show "Last sync result (this session)" only. If request fails/error returned: "Neo4j unavailable. Local graph unaffected." Disabled in All-repos scope (API is per-repo) with tooltip. Writes with 401/403: banner "API token required - set GRAPHIFIER_API_TOKEN on the server"; client stores bearer in memory/sessionStorage via settings popover field, sent as Authorization header; never in bundle.

Other honest states: API down banner; graph loading skeleton rows (no fake data); empty graph after completed job: "No lineage entities found in indexed files"; partial/unresolved visible as amber nodes + rail count; no env set: inline prompt; evidence 404: "Snapshot file unavailable".

## 8. Interaction/keyboard
`/` search, `]` toggle inspector, `Esc` clear focus/selection, `u`/`d` set upstream/downstream for selected node, `f` fit. All controls focusable with --focus ring; dialogs trap focus; aria-labels on icon buttons; chips carry text. Respect prefers-reduced-motion (no spinner easing tricks). Transitions <=120ms.

## 9. Component/file layout
```
app/layout.tsx, app/page.tsx (client shell), app/globals.css (tokens)
lib/api.ts (typed fetch, error->detail), lib/types.ts, lib/useJobPolling.ts, lib/layout.ts
components/shell/{TopBar,LeftRail,Inspector,ResizeHandle,Toast}.tsx
components/repos/{RepoList,FolderBrowserDialog,Onboarding}.tsx
components/jobs/{JobList,RunAnalysisDialog,StatusChip}.tsx
components/graph/{LineageCanvas,NodeCard,EdgeLabel,GraphToolbar,FocusList}.tsx
components/evidence/{EvidenceList,CodeViewer}.tsx
components/mapping/{SymbolList,BindingForm,PreviewPanel,ConflictList}.tsx
```
State: one small store (zustand not installed -> React context + useReducer) holding repoId, environment, scope, selection {node|edge}, focus, direction. Fetch with plain fetch + AbortController; no mock data anywhere.

## 10. Gaps to flag, not invent
No environments list, node search, job-environment field, Neo4j status GET, or job-mode field returned by API; UI handles these client-side as above. Resolution preview shape is unspecified in API.md: use generic renderer.
