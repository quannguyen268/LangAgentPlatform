# Phase 2B-II: Web UI v1 (Dashboard-First MVP) — Design Spec

**Date:** 2026-05-17
**Phase:** 2B-II (second slice of Phase 2B)
**Predecessor:** Phase 2B-I (`v0.5.0-phase2b-i`)
**Successor:** Phase 3 — depends on this slice
**Spec reference:** `docs/superpowers/specs/2026-04-15-langagent-platform-design.md` §20

---

## 1. Goal

Ship a React management dashboard that consumes the Phase 2B-I read-only API. The v1 is a **single-page, no-router, no-auth localhost dashboard** with five panels: Agents, Teams, Tasks, Cost, and Live Events. WebSocket events feed real-time invalidation of cached server state.

**Out of scope for v1:**
- **Chat panel** — chat already has multiple working channels (Telegram/CLI/API); the Web UI is positioned as a management console per spec §20.1.
- **Settings page** — memory files are editable directly; deferred to later iteration if needed.
- **Task board (Kanban) view** — the board projection was deferred from Phase 2B-I; v1 stays with a simple Tasks list.
- **Git activity view** — needs new backend plumbing.
- **Authentication** — matches Phase 2B-I (localhost-only, no auth, non-loopback WARN from `APIChannel`).
- **Multi-user, JWT, RBAC** — Phase 3 if needed.
- **Storybook, Playwright e2e** — Vitest + React Testing Library only.
- **Optimistic updates** — read-only API; reads only.

## 2. Decomposition rationale

The original Phase 2B (per spec §20.8) bundled chat channels + management API + Web UI. Phase 2B-I (just shipped) extracted the API. Phase 2B-II ships only the Dashboard pane of the Web UI v1; Chat and Settings would be follow-ons.

The "Dashboard-first MVP" cut is justified because:

1. The spec itself calls the Web UI a management console (§20.1), and the Dashboard is the management console's main view.
2. Chat already works through three channels; a fourth chat surface is duplicate effort.
3. Every panel in the v1 dashboard maps onto an endpoint that already exists. Zero new backend work.
4. ~12 tasks vs ~25+ for full v1 (matches Phase 2B-I's task count).

## 3. Tech stack

- **Vite + React 18 + TypeScript** — pure SPA; no SSR, no file-based routing, no RSC. Build emits a static `dist/` that aiohttp serves.
- **TailwindCSS + shadcn/ui** — utility CSS + a small set of pre-styled primitives (`Card`, `Drawer`, `Badge`, `Button`).
- **TanStack Query v5** — server state (REST cache, stale-while-revalidate, query invalidation as the WebSocket sync primitive).
- **Plain React `useState`** — UI state (selected agent for detail drawer, banner state). No Zustand in v1.
- **Recharts** — cost-over-time line chart on the Cost panel.
- **Vitest + @testing-library/react** — unit tests.
- **No router.** Single page; layout is a 2×2 grid + persistent right rail (chosen during brainstorming, layout option C).

## 4. Architecture

### 4.1 File layout

```
web/                                  # NEW top-level (peer of src/, tests/)
├── package.json
├── vite.config.ts                    # build → ../src/api/static/, dev proxy /v1 + /ws → :8900
├── tsconfig.json
├── tailwind.config.ts
├── postcss.config.js
├── index.html
├── src/
│   ├── main.tsx                      # Mount + QueryClientProvider + WebSocketProvider
│   ├── App.tsx                       # 2×2 grid + right rail
│   ├── api/
│   │   ├── client.ts                 # fetch wrapper (base URL = '', same-origin)
│   │   ├── types.ts                  # Hand-written from spec §4
│   │   ├── agents.ts                 # useAgents(), useAgentDetail(id)
│   │   ├── teams.ts                  # useTeams()
│   │   ├── tasks.ts                  # useTasks()
│   │   ├── cost.ts                   # useCostBreakdown()
│   │   └── config.ts                 # useConfig()  (referenced by Cost panel)
│   ├── ws/
│   │   ├── provider.tsx              # WebSocketProvider — opens /ws + context fan-out
│   │   └── invalidator.ts            # event_type → list of queryKey to invalidate
│   └── panels/
│       ├── AgentsPanel.tsx
│       ├── TeamsPanel.tsx
│       ├── TasksPanel.tsx
│       ├── CostPanel.tsx
│       └── LiveEventsPanel.tsx
├── tests/                            # Vitest + RTL
│   ├── api.test.ts
│   ├── ws.test.tsx
│   └── panels/
│       ├── AgentsPanel.test.tsx
│       ├── TeamsPanel.test.tsx
│       ├── TasksPanel.test.tsx
│       ├── CostPanel.test.tsx
│       └── LiveEventsPanel.test.tsx
└── dist/                             # Vite build output (gitignored)
```

### 4.2 Backend changes

Limited to deployment plumbing:

- `src/channels/api.py` — accept a new `web_dist_path: str | None = None` kwarg on `APIChannel.__init__`. In `_register_routes`, when set, mount:
  - `GET /` → 302 redirect to `/web/`
  - `GET /web/{tail:.*}` → static file handler rooted at `web_dist_path`
- `src/main.py` — compute `web_dist_path = Path(__file__).parent / "api" / "static"`; pass to `APIChannel` only if the directory exists (so dev runs without the bundle still work).
- `src/api/static/` — Vite build output target. Directory is created by `npm run build`; gitignored.

No changes to existing route handlers, schemas, or business logic.

### 4.3 Layout (chosen during brainstorming, option C)

```
┌────────────────────────────────────────────────────────┬──────────────┐
│  Agents (3)             │  Teams (1)                   │              │
│  · backend-dev running  │  · team-7e2c execute 3       │  Live Events │
│  · tester finished      │                              │  ──────────  │
│  · architect running    │                              │  14:05 spawn │
├─────────────────────────┼──────────────────────────────┤  14:05 prog. │
│  Tasks (2)              │  Cost                        │  14:06 spawn │
│  · daily-standup        │  ▁▃▅█▆▄▂▁▂▄  $1.24/d         │  14:07 done  │
│  · cleanup-temp         │                              │  …           │
└─────────────────────────┴──────────────────────────────┴──────────────┘
```

Click an agent row → right-side drawer overlays with detail. Drawer closes on Esc or backdrop click.

## 5. Data flow

### 5.1 REST (steady state)

```
mount App
  → QueryClient (staleTime=30s, refetchOnWindowFocus=false)
  → AgentsPanel renders → useAgents() → GET /v1/agents
  → Result cached at queryKey ['agents']
  → 30s stale → background refetch on next render
```

### 5.2 WebSocket (real-time invalidation)

Provider tree in `main.tsx` — the WebSocketProvider must be a child of
QueryClientProvider so it can call `useQueryClient()`:

```tsx
<QueryClientProvider client={queryClient}>
  <WebSocketProvider>
    <App />
  </WebSocketProvider>
</QueryClientProvider>
```

Provider behavior:

```
WebSocketProvider mounts
  → connect to ws://<same-origin>/ws
  → on message:
      lookup invalidator[event.type] → list of queryKey
      for each key: queryClient.invalidateQueries({ queryKey: key })
  → on disconnect: log + reconnect with exponential backoff
      (1s, 2s, 4s, 8s, 16s, capped at 30s)
  → emit reconnection state via context for the LiveEventsPanel banner
```

The `invalidator.ts` table is the single source of truth for "which event invalidates what":

```ts
export const INVALIDATOR: Record<string, QueryKey[]> = {
  agent_spawn:    [['agents']],
  agent_progress: [['agents']],
  agent_complete: [['agents'], ['cost']],
  agent_failed:   [['agents'], ['cost']],
  cost_update:    [['cost']],
  team_created:   [['teams']],
  task_scheduled: [['tasks']],
  task_cancelled: [['tasks']],
};
```

(Unknown event types are logged at DEBUG and ignored — keeps the dashboard resilient to backend additions.)

### 5.3 LiveEventsPanel exception

LiveEventsPanel keeps its own in-memory ring buffer (last 50 events) — it's the only consumer that needs the raw event stream. Subscribes via `useContext(WebSocketContext)` rather than via TanStack Query.

## 6. Empty states & error handling

Each panel handles three rendering states:

- **Loading** — shadcn `Skeleton` placeholder rows.
- **Empty list** — friendly message ("No active sub-agents"). Spec §4.8 explicitly returns `{"agents": []}` (etc.) when subsystems are disabled; the UI renders the same empty state regardless of cause.
- **Error** — `Card` with the OpenAI envelope's `message` (if present) + a Retry button that triggers `refetch()`.

WebSocket disconnections show a small "reconnecting…" badge in the LiveEventsPanel header. No global banner.

`/v1/config` 503 (config_unavailable) doesn't appear in v1 UI because no panel queries `/v1/config` directly — Cost panel uses `/v1/cost/breakdown` only. Future panels that consume `/v1/config` should render a dedicated "config not wired" card.

## 7. Testing strategy

- **Vitest + @testing-library/react** for component tests; one test file per panel.
- **Mocked `fetch`** for API hook tests (no MSW for v1; mocked fetch is enough at this scale).
- **Mock `WebSocket`** for the WebSocketProvider test — assert that pushing each event type invalidates the documented query keys.
- **Recharts components stubbed** in CostPanel tests (e.g., mock the `<LineChart>` child to assert data was passed correctly without rendering SVG).
- **No e2e in v1.** A future Phase 2C may add Playwright once we have a stable feature surface.

Python side keeps its existing 870-pass / 6-pre-existing-fail baseline. Two additions:
- `tests/test_api_channel_wiring.py` extended with two cases for the `/web/*` static handler + `/` redirect.
- `tests/test_main_static_path.py` (new) verifies `main.py` only sets `web_dist_path` when the directory exists.

## 8. Exit criteria

- 5 panels render with live data on a running platform (`localhost:8900/`).
- WebSocket reconnect demonstrated (kill server, restart, panel reconnects within 30s, banner clears).
- Detail drawer renders agent detail on row click; closes on Esc.
- Cost panel renders a time-series chart over `/v1/cost/breakdown`.
- LiveEventsPanel shows the most recent 50 events; oldest evicted FIFO.
- Vite production build (`npm run build`) emits to `src/api/static/`; aiohttp serves it.
- Full Python suite at the existing 6-pre-existing-fail baseline; zero new failures.
- New Vitest suite ≥20 tests, all green.
- Plan README updated to mark 2B-II done.
- Tag `v0.6.0-phase2b-ii` pushed.

## 9. Estimated task count

12 tasks. Detailed task breakdown moves to the implementation plan at `docs/superpowers/plans/2026-05-17-phase2b-ii-web-ui.md`.

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Vite + aiohttp dev loop friction (CORS, ports) | Vite dev server proxies `/v1` + `/ws` to `localhost:8900`; production build bakes same-origin URLs. Both modes use base URL `""`. |
| WebSocket reconnect storm during backend restart | Exponential backoff capped at 30s; banner shows live status. Tested by injecting close events into the provider in unit tests. |
| Bundle size growth as shadcn components proliferate | Tailwind purge is automatic; shadcn components are copy-pasted (not a runtime dep). Size review at T11 before tagging. |
| Recharts dragging in moment/lodash transitively | Recharts dropped moment in v2.x; verify with `npm ls` at T8. |
| `web/` directory churn affecting Python repo signal | All Python tests untouched. `web/dist/` and `src/api/static/` gitignored. |
| TypeScript types drifting from spec §4 | Contract tests on the Python side already pin the response shapes. UI tests assert the shape they consume; mismatch surfaces in CI. Future hardening: generate types from a schema. |
| WebSocket invalidator table grows stale as backend adds events | Unknown events log at DEBUG; spec change → add to invalidator + add test. Phase 2C may add a registry pattern. |

---

**End of spec.**
