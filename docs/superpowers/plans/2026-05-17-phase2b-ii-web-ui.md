# Phase 2B-II: Web UI v1 (Dashboard-First MVP) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a React management dashboard at `localhost:8900/` that mirrors live platform state via the Phase 2B-I REST endpoints and the `/ws` WebSocket. Five panels: Agents, Teams, Tasks, Cost, Live Events. No router, no auth, localhost-only.

**Architecture:** A new top-level `web/` directory hosts a Vite + React + TypeScript SPA. TanStack Query owns server state; the WebSocketProvider opens `/ws` and dispatches `invalidateQueries` calls keyed by event type. `npm run build` emits to `src/api/static/`, which `APIChannel` serves via a new `/web/*` static handler with `/` redirecting to `/web/`. The Python suite stays untouched apart from two small additions to `src/channels/api.py` and `src/main.py`.

**Tech Stack:** Vite 5 + React 18 + TypeScript 5, TailwindCSS 3 + shadcn/ui primitives (copy-pasted, not a runtime dep), @tanstack/react-query 5, Recharts 2, Vitest 1 + @testing-library/react + jsdom for component tests.

**Spec Reference:** `docs/superpowers/specs/2026-05-17-phase2b-ii-web-ui-design.md`

**Prerequisites:** Phase 2B-I complete (`v0.5.0-phase2b-i`, 870 tests / 6 pre-existing failures). Depends on:
- `/v1/agents`, `/v1/agents/{id}`, `/v1/teams`, `/v1/tasks`, `/v1/config`, `/v1/cost/breakdown` endpoints (Phase 2B-I + Phase 1B)
- `/ws` WebSocket emitting `agent_spawn` / `agent_progress` / `agent_complete` / `agent_failed` events (Phase 2A T13)
- `APIChannel` with the existing `_register_routes` extraction (Phase 2B-I T10)
- Node 20+ and npm 10+ available on the host machine

---

## File Structure

### New files

```
web/                                     # NEW top-level (peer of src/, tests/)
├── .gitignore                           # node_modules + dist
├── package.json
├── package-lock.json                    # committed
├── vite.config.ts
├── tsconfig.json
├── tsconfig.node.json                   # for vite.config.ts
├── tailwind.config.ts
├── postcss.config.js
├── index.html
├── vitest.config.ts                     # extends vite.config + jsdom
├── src/
│   ├── main.tsx                         # mount + QueryClientProvider + WebSocketProvider
│   ├── App.tsx                          # 2×2 grid + right rail
│   ├── index.css                        # tailwind directives + shadcn variables
│   ├── lib/
│   │   └── cn.ts                        # shadcn classNames helper
│   ├── components/ui/                   # shadcn primitives, copy-pasted
│   │   ├── card.tsx
│   │   ├── badge.tsx
│   │   ├── button.tsx
│   │   ├── skeleton.tsx
│   │   └── drawer.tsx
│   ├── api/
│   │   ├── client.ts                    # fetch wrapper
│   │   ├── types.ts                     # TS types from spec §4
│   │   ├── agents.ts                    # useAgents() + useAgentDetail(id)
│   │   ├── teams.ts                     # useTeams()
│   │   ├── tasks.ts                     # useTasks()
│   │   ├── cost.ts                      # useCostBreakdown()
│   │   └── config.ts                    # useConfig()
│   ├── ws/
│   │   ├── invalidator.ts               # event_type → queryKey[]
│   │   └── provider.tsx                 # WebSocketProvider + useWebSocketStatus
│   └── panels/
│       ├── AgentsPanel.tsx
│       ├── AgentDetailDrawer.tsx
│       ├── TeamsPanel.tsx
│       ├── TasksPanel.tsx
│       ├── CostPanel.tsx
│       └── LiveEventsPanel.tsx
└── tests/
    ├── setup.ts                         # @testing-library/jest-dom matchers
    ├── api.test.ts                      # client + hooks (mocked fetch)
    ├── ws.test.tsx                      # provider + invalidator
    └── panels/
        ├── AgentsPanel.test.tsx
        ├── TeamsPanel.test.tsx
        ├── TasksPanel.test.tsx
        ├── CostPanel.test.tsx
        └── LiveEventsPanel.test.tsx

tests/test_api_static_serving.py         # Python-side: /web/* + / redirect
tests/test_main_static_path.py           # Python-side: main.py guards
```

### Modified files

```
.gitignore                                # add web/node_modules, web/dist, src/api/static/
src/channels/api.py                       # accept web_dist_path kwarg; mount /web/* + / redirect
src/main.py                               # pass web_dist_path when src/api/static/ exists
docs/superpowers/plans/README.md          # mark Phase 2B-II DONE (T12)
```

`src/api/static/` is the Vite production build output — created by `npm run build`, gitignored.

---

### Task 1: Scaffold `web/` with Vite + React + TS + Tailwind + shadcn

**Files:**
- Create: `web/package.json`, `web/vite.config.ts`, `web/vitest.config.ts`, `web/tsconfig.json`, `web/tsconfig.node.json`, `web/tailwind.config.ts`, `web/postcss.config.js`, `web/index.html`, `web/.gitignore`
- Create: `web/src/main.tsx`, `web/src/App.tsx`, `web/src/index.css`, `web/src/lib/cn.ts`
- Create: `web/tests/setup.ts`, `web/tests/App.test.tsx`
- Modify: `.gitignore` (add `web/node_modules`, `web/dist`, `src/api/static/`)

Goal: a single passing Vitest assertion that App renders the placeholder text. Establishes the build + test infrastructure.

- [ ] **Step 1: Write the failing test**

`web/tests/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

`web/tests/App.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "../src/App";

describe("App", () => {
  it("renders the dashboard title", () => {
    render(<App />);
    expect(screen.getByText(/LangAgent Dashboard/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Bootstrap package.json + configs**

`web/package.json`:

```json
{
  "name": "langagent-web",
  "private": true,
  "version": "0.0.1",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.40.0",
    "clsx": "^2.1.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "recharts": "^2.12.0",
    "tailwind-merge": "^2.3.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.0",
    "@testing-library/react": "^16.0.0",
    "@testing-library/user-event": "^14.5.0",
    "@types/node": "^20.12.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "autoprefixer": "^10.4.0",
    "jsdom": "^24.0.0",
    "postcss": "^8.4.0",
    "tailwindcss": "^3.4.0",
    "typescript": "^5.4.0",
    "vite": "^5.2.0",
    "vitest": "^1.6.0"
  }
}
```

`web/.gitignore`:

```
node_modules
dist
*.log
.DS_Store

# tsc -b outputs (we run with allowImportingTsExtensions; no need to track)
*.tsbuildinfo
vite.config.d.ts
vite.config.js
vitest.config.d.ts
vitest.config.js
```

`web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] }
  },
  "include": ["src", "tests"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

`web/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "types": ["node"]
  },
  "include": ["vite.config.ts", "vitest.config.ts"]
}
```

`web/vite.config.ts`:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/v1": "http://localhost:8900",
      "/ws": { target: "ws://localhost:8900", ws: true },
    },
  },
  build: {
    // Production output target — aiohttp serves this directory.
    outDir: path.resolve(__dirname, "../src/api/static"),
    emptyOutDir: true,
    // Assets resolve under /web/ in production.
    assetsDir: "assets",
  },
  base: "/web/",
});
```

`web/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    globals: false,
  },
});
```

`web/tailwind.config.ts`:

```ts
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        muted: "hsl(var(--muted))",
        "muted-foreground": "hsl(var(--muted-foreground))",
        accent: "hsl(var(--accent))",
      },
    },
  },
  plugins: [],
} satisfies Config;
```

`web/postcss.config.js`:

```js
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

`web/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>LangAgent Dashboard</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`web/src/index.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --background: 0 0% 100%;
  --foreground: 222 47% 11%;
  --muted: 210 40% 96%;
  --muted-foreground: 215 16% 47%;
  --accent: 210 40% 96%;
  --border: 214 32% 91%;
}

@media (prefers-color-scheme: dark) {
  :root {
    --background: 222 47% 11%;
    --foreground: 210 40% 98%;
    --muted: 217 33% 17%;
    --muted-foreground: 215 20% 65%;
    --accent: 217 33% 17%;
    --border: 217 33% 17%;
  }
}

body {
  @apply bg-background text-foreground;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
```

`web/src/lib/cn.ts`:

```ts
import clsx, { type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
```

`web/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

`web/src/App.tsx`:

```tsx
export default function App() {
  return (
    <main className="min-h-screen p-6">
      <h1 className="text-2xl font-semibold">LangAgent Dashboard</h1>
      <p className="text-muted-foreground mt-2">v1 scaffolding.</p>
    </main>
  );
}
```

Append to root `.gitignore`:

```
web/node_modules
web/dist
src/api/static/
.superpowers/
```

(`.superpowers/` may already be present from brainstorming — keep one entry only.)

- [ ] **Step 3: Install dependencies and run the test**

```bash
cd web && npm install
npm test
```

Expected: 1 passed.

- [ ] **Step 4: Verify `npm run dev` boots**

```bash
cd web && timeout 5 npm run dev > /tmp/vite.log 2>&1 || true
grep -q "Local:" /tmp/vite.log && echo "vite dev OK"
```

Expected: `vite dev OK`.

- [ ] **Step 4b: Verify production build**

```bash
cd web && npm run build && test -f ../src/api/static/index.html && echo "build OK"
```

Expected: `build OK`.

- [ ] **Step 5: Commit**

```bash
git add web/ .gitignore
git commit -m "feat(web): scaffold Vite + React + TS + Tailwind dashboard skeleton"
```

---

### Task 2: Backend wiring — `/web/*` static handler + `/` redirect

**Files:**
- Modify: `src/channels/api.py` — accept `web_dist_path: str | None` kwarg; mount routes in `_register_routes`
- Create: `tests/test_api_static_serving.py`

`web_dist_path` is None by default; when set to an existing directory, mount the static handler. Keeps existing tests untouched and the dev loop functional without a build.

- [ ] **Step 1: Write the failing test**

`tests/test_api_static_serving.py`:

```python
"""Test APIChannel serves the Vite dist at /web/* and redirects / → /web/."""
import logging
from pathlib import Path

import pytest
from aiohttp import web


@pytest.mark.asyncio
async def test_static_handler_serves_index_html(tmp_path, aiohttp_client):
    """When web_dist_path is set, GET /web/ returns the index.html content."""
    from src.channels.api import APIChannel

    dist = tmp_path / "static"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>hello dashboard</body></html>")

    ch = APIChannel(host="127.0.0.1", port=0, web_dist_path=str(dist))
    app = web.Application()
    ch._register_routes(app)
    client = await aiohttp_client(app)

    resp = await client.get("/web/")
    assert resp.status == 200
    body = await resp.text()
    assert "hello dashboard" in body


@pytest.mark.asyncio
async def test_static_handler_serves_nested_asset(tmp_path, aiohttp_client):
    from src.channels.api import APIChannel

    dist = tmp_path / "static"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "main.js").write_text("console.log('ok');")

    ch = APIChannel(host="127.0.0.1", port=0, web_dist_path=str(dist))
    app = web.Application()
    ch._register_routes(app)
    client = await aiohttp_client(app)

    resp = await client.get("/web/assets/main.js")
    assert resp.status == 200
    body = await resp.text()
    assert "console.log" in body


@pytest.mark.asyncio
async def test_root_redirects_to_web(tmp_path, aiohttp_client):
    from src.channels.api import APIChannel

    dist = tmp_path / "static"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>")

    ch = APIChannel(host="127.0.0.1", port=0, web_dist_path=str(dist))
    app = web.Application()
    ch._register_routes(app)
    client = await aiohttp_client(app)

    resp = await client.get("/", allow_redirects=False)
    assert resp.status in (301, 302)
    assert resp.headers["Location"] == "/web/"


@pytest.mark.asyncio
async def test_no_web_routes_when_dist_path_not_set(aiohttp_client):
    """When web_dist_path is None, /web/ and / return 404 (no static handler)."""
    from src.channels.api import APIChannel

    ch = APIChannel(host="127.0.0.1", port=0)  # web_dist_path defaults to None
    app = web.Application()
    ch._register_routes(app)
    client = await aiohttp_client(app)

    resp = await client.get("/web/")
    assert resp.status == 404
    resp = await client.get("/", allow_redirects=False)
    assert resp.status == 404


def test_apichannel_logs_static_serve_path(tmp_path, caplog):
    """Operators should see at INFO which directory is being served, to debug
    mismatches between build output and configured path."""
    from src.channels.api import APIChannel

    dist = tmp_path / "static"
    dist.mkdir()
    ch = APIChannel(host="127.0.0.1", port=0, web_dist_path=str(dist))
    with caplog.at_level(logging.INFO, logger="src.channels.api"):
        app = web.Application()
        ch._register_routes(app)
    assert any(str(dist) in r.message for r in caplog.records)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_api_static_serving.py -v
```

Expected: FAIL — `APIChannel.__init__()` does not accept `web_dist_path`.

- [ ] **Step 3: Extend APIChannel**

In `src/channels/api.py`:

Update `__init__` signature (add `web_dist_path` after `config`):

```python
    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8900,
        workspace=None,
        cost_tracker=None,
        event_hub=None,
        subagent_registry=None,
        swarm=None,
        config=None,
        web_dist_path: str | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._workspace = workspace
        self._cost_tracker = cost_tracker
        self._event_hub = event_hub
        self._subagent_registry = subagent_registry
        self._swarm = swarm
        self._config = config
        self._web_dist_path = web_dist_path
        self._callback = None
        self._runner: web.AppRunner | None = None
        self._response_queues: dict[str, asyncio.Queue] = {}
```

Add helper handlers near the other private methods:

```python
    async def _handle_root_redirect(self, request: web.Request) -> web.Response:
        """Redirect / to /web/ so operators landing on the bare host see the dashboard."""
        raise web.HTTPFound("/web/")

    async def _handle_web_index(self, request: web.Request) -> web.FileResponse:
        """Serve index.html for the bare /web/ URL.

        aiohttp's ``add_static`` does NOT auto-serve index.html for directory
        URLs (the ``show_index`` flag controls listing, not index resolution).
        We need an explicit handler that returns ``index.html`` from the dist
        root so the SPA boots when the user visits /web/.
        """
        from pathlib import Path
        assert self._web_dist_path  # guarded by the caller
        return web.FileResponse(Path(self._web_dist_path) / "index.html")
```

In `_register_routes`, AFTER the existing 2B-I management routes, BEFORE the function returns, add:

```python
        # Phase 2B-II Web UI: static file serving + root redirect.
        # Only wire up when the dist directory exists and was passed by main.py.
        if self._web_dist_path:
            from pathlib import Path
            dist = Path(self._web_dist_path)
            if dist.is_dir():
                logger.info("APIChannel: serving web UI from %s", dist)
                app.router.add_get("/", self._handle_root_redirect)
                # Explicit /web/ handler returns index.html (aiohttp's add_static
                # does not auto-resolve directory URLs to index files).
                app.router.add_get("/web/", self._handle_web_index)
                # Static assets at /web/* — show_index=False prevents the dist
                # directory contents being listed if someone hits /web/assets/.
                app.router.add_static(
                    "/web/", path=str(dist),
                    show_index=False, append_version=False,
                )
            else:
                logger.warning(
                    "APIChannel: web_dist_path %s does not exist; skipping web UI routes",
                    dist,
                )
```

The route registration order matters: aiohttp tries routes in the order they
were added, so the explicit `GET /web/` handler must be registered BEFORE
`add_static("/web/", ...)`. Otherwise the static handler would match `/web/`
first and return a 404 (no `index.html` resolution).

- [ ] **Step 4: Run tests to verify they pass + full-suite regression**

```bash
pytest tests/test_api_static_serving.py -v
pytest tests/ -q --tb=line --ignore=tests/test_middleware_bridge.py --ignore=tests/test_middleware_full.py 2>&1 | tail -5
```

Expected: 5 new tests pass; full suite at the 6-pre-existing baseline + 5 new passing.

- [ ] **Step 5: Commit**

```bash
git add src/channels/api.py tests/test_api_static_serving.py
git commit -m "feat(api): serve Vite dist at /web/* with / → /web/ redirect"
```

---

### Task 3: API types + client + hooks

**Files:**
- Create: `web/src/api/client.ts`, `web/src/api/types.ts`, `web/src/api/agents.ts`, `web/src/api/teams.ts`, `web/src/api/tasks.ts`, `web/src/api/cost.ts`, `web/src/api/config.ts`
- Create: `web/tests/api.test.ts`

Hand-written TypeScript types mirror Phase 2B-I spec §4 shapes. The `client.ts` wrapper handles JSON + error envelope unwrapping. Each `useX()` hook is a thin TanStack Query wrapper.

- [ ] **Step 1: Write the failing test**

`web/tests/api.test.ts`:

```ts
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import React from "react";

import { apiGet, ApiError } from "../src/api/client";
import { useAgents } from "../src/api/agents";

const ORIGINAL_FETCH = globalThis.fetch;

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
}

describe("apiGet", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn() as unknown as typeof fetch;
  });
  afterEach(() => {
    globalThis.fetch = ORIGINAL_FETCH;
  });

  it("returns parsed JSON on 200", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: 1 }), { status: 200 }),
    );
    const out = await apiGet<{ ok: number }>("/v1/test");
    expect(out).toEqual({ ok: 1 });
  });

  it("throws ApiError with envelope details on 4xx/5xx", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: { message: "no such agent", type: "not_found", code: "agent_not_found" },
        }),
        { status: 404 },
      ),
    );
    await expect(apiGet("/v1/agents/missing")).rejects.toMatchObject({
      status: 404,
      code: "agent_not_found",
      message: "no such agent",
    });
  });

  it("throws ApiError when response is not JSON", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response("not json", { status: 500 }),
    );
    await expect(apiGet("/v1/test")).rejects.toBeInstanceOf(ApiError);
  });
});

describe("useAgents", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn() as unknown as typeof fetch;
  });
  afterEach(() => {
    globalThis.fetch = ORIGINAL_FETCH;
  });

  it("loads the agents list", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          agents: [
            {
              agent_id: "a-1", name: "n", role: "executor", tier: "standard",
              state: "running", task: "t", tools: [], skills: [],
              iteration: 0, cost_cents: 0, retry_count: 0,
              created_at: "2026-05-17T00:00:00Z",
              last_heartbeat: "2026-05-17T00:00:00Z",
              finished_at: null,
            },
          ],
        }),
        { status: 200 },
      ),
    );
    const { result } = renderHook(() => useAgents(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.agents).toHaveLength(1);
    expect(result.current.data?.agents[0].agent_id).toBe("a-1");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd web && npm test -- api.test.ts
```

Expected: FAIL — `src/api/client.ts` does not exist.

- [ ] **Step 3: Write the types, client, and hooks**

`web/src/api/types.ts`:

```ts
// Mirrors spec §4 shapes from docs/superpowers/specs/2026-04-29-phase2b-i-management-api-design.md.
// Hand-written; if the contract drifts the panel tests will surface it.

export type AgentState =
  | "spawning" | "ready" | "running" | "blocked" | "finished" | "failed";

export interface AgentSummary {
  agent_id: string;
  name: string;
  role: string;
  tier: string;
  state: AgentState;
  task: string;
  tools: string[];
  skills: string[];
  iteration: number;
  cost_cents: number;
  retry_count: number;
  created_at: string;
  last_heartbeat: string;
  finished_at: string | null;
}

export interface AgentDetail extends AgentSummary {
  error: string | null;
}

export interface AgentsListResponse { agents: AgentSummary[]; }

export interface TeamSummary {
  team_id: string;
  phases: string[];
  current_phase: string | null;
  is_finished: boolean;
  agent_count: number;
  agent_ids: string[];
}
export interface TeamsListResponse { teams: TeamSummary[]; }

export interface TaskSummary {
  task_id: string;
  prompt: string;
  schedule_type: "cron" | "interval" | "once" | string;
  schedule_value: string;
  model_tier: string | null;
  next_run: string | null;
  created_at: string;
}
export interface TasksListResponse { tasks: TaskSummary[]; }

export interface CostBreakdown {
  by_user: Record<string, number>;
  by_tier: Record<string, number>;
  by_agent: Record<string, number>;
}

// Config is shaped at runtime; we don't type every field. The Cost panel
// pulls only the budget settings, so a permissive type is fine.
export interface ConfigResponse {
  [section: string]: unknown;
}

export interface ApiErrorEnvelope {
  error: { message: string; type: string; code: string };
}
```

`web/src/api/client.ts`:

```ts
export class ApiError extends Error {
  status: number;
  code: string;
  type: string;
  constructor(status: number, type: string, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.type = type;
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(path, { headers: { Accept: "application/json" } });
  let body: unknown;
  try {
    body = await resp.json();
  } catch {
    throw new ApiError(resp.status, "internal_error", "non_json_response",
      `Non-JSON response from ${path} (${resp.status})`);
  }
  if (!resp.ok) {
    const envelope = body as { error?: { type?: string; code?: string; message?: string } };
    const err = envelope.error ?? {};
    throw new ApiError(
      resp.status,
      err.type ?? "internal_error",
      err.code ?? "unknown",
      err.message ?? `Request to ${path} failed (${resp.status})`,
    );
  }
  return body as T;
}
```

`web/src/api/agents.ts`:

```ts
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiGet } from "./client";
import type { AgentsListResponse, AgentDetail } from "./types";

export function useAgents(): UseQueryResult<AgentsListResponse, Error> {
  return useQuery({
    queryKey: ["agents"],
    queryFn: () => apiGet<AgentsListResponse>("/v1/agents"),
    staleTime: 30_000,
  });
}

export function useAgentDetail(agentId: string | null): UseQueryResult<AgentDetail, Error> {
  return useQuery({
    queryKey: ["agents", agentId],
    queryFn: () => apiGet<AgentDetail>(`/v1/agents/${agentId}`),
    enabled: agentId !== null,
    staleTime: 30_000,
  });
}
```

`web/src/api/teams.ts`:

```ts
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiGet } from "./client";
import type { TeamsListResponse } from "./types";

export function useTeams(): UseQueryResult<TeamsListResponse, Error> {
  return useQuery({
    queryKey: ["teams"],
    queryFn: () => apiGet<TeamsListResponse>("/v1/teams"),
    staleTime: 30_000,
  });
}
```

`web/src/api/tasks.ts`:

```ts
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiGet } from "./client";
import type { TasksListResponse } from "./types";

export function useTasks(): UseQueryResult<TasksListResponse, Error> {
  return useQuery({
    queryKey: ["tasks"],
    queryFn: () => apiGet<TasksListResponse>("/v1/tasks"),
    staleTime: 30_000,
  });
}
```

`web/src/api/cost.ts`:

```ts
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiGet } from "./client";
import type { CostBreakdown } from "./types";

export function useCostBreakdown(): UseQueryResult<CostBreakdown, Error> {
  return useQuery({
    queryKey: ["cost"],
    queryFn: () => apiGet<CostBreakdown>("/v1/cost/breakdown"),
    staleTime: 30_000,
  });
}
```

`web/src/api/config.ts`:

```ts
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiGet } from "./client";
import type { ConfigResponse } from "./types";

export function useConfig(): UseQueryResult<ConfigResponse, Error> {
  return useQuery({
    queryKey: ["config"],
    queryFn: () => apiGet<ConfigResponse>("/v1/config"),
    staleTime: 60_000,
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd web && npm test -- api.test.ts
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add web/src/api web/tests/api.test.ts
git commit -m "feat(web): API client + hooks + types mirroring Phase 2B-I spec §4"
```

---

### Task 4: WebSocketProvider + invalidator

**Files:**
- Create: `web/src/ws/invalidator.ts`, `web/src/ws/provider.tsx`
- Create: `web/tests/ws.test.tsx`

The invalidator is a plain table — testable as a pure function. The provider wires the WebSocket to it and exposes connection status via context for the LiveEventsPanel reconnect banner.

- [ ] **Step 1: Write the failing test**

`web/tests/ws.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, act, waitFor } from "@testing-library/react";
import React from "react";

import {
  WebSocketProvider,
  useWebSocketStatus,
} from "../src/ws/provider";
import { INVALIDATOR, keysFor } from "../src/ws/invalidator";

// ---------- invalidator table (pure function tests) ----------

describe("INVALIDATOR table", () => {
  it("maps agent lifecycle events to the agents query key", () => {
    expect(keysFor("agent_spawn")).toEqual([["agents"]]);
    expect(keysFor("agent_progress")).toEqual([["agents"]]);
  });

  it("maps agent_complete and agent_failed to agents + cost", () => {
    expect(keysFor("agent_complete")).toEqual([["agents"], ["cost"]]);
    expect(keysFor("agent_failed")).toEqual([["agents"], ["cost"]]);
  });

  it("maps cost_update to cost", () => {
    expect(keysFor("cost_update")).toEqual([["cost"]]);
  });

  it("returns empty list for unknown event types", () => {
    expect(keysFor("nonsense_event_42")).toEqual([]);
  });

  it("table covers every event type listed in spec §5.2", () => {
    for (const ev of [
      "agent_spawn", "agent_progress", "agent_complete", "agent_failed",
      "cost_update", "team_created", "task_scheduled", "task_cancelled",
    ]) {
      expect(INVALIDATOR[ev]).toBeDefined();
    }
  });
});

// ---------- provider tests with a stubbed WebSocket ----------

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  url: string;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  readyState = 0;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }
  close() { this.closed = true; }
  // Test helpers
  _open() { this.readyState = 1; this.onopen?.(new Event("open")); }
  _msg(data: object) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) }));
  }
  _disconnect() {
    this.readyState = 3;
    this.onclose?.(new CloseEvent("close"));
  }
}

function StatusProbe() {
  const status = useWebSocketStatus();
  return <span data-testid="status">{status}</span>;
}

describe("WebSocketProvider", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    // @ts-expect-error overriding global for the test
    globalThis.WebSocket = FakeWebSocket;
  });
  afterEach(() => {
    FakeWebSocket.instances = [];
  });

  it("opens a WebSocket on mount and exposes 'connected' status when open fires", async () => {
    const qc = new QueryClient();
    const { getByTestId } = render(
      <QueryClientProvider client={qc}>
        <WebSocketProvider>
          <StatusProbe />
        </WebSocketProvider>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => FakeWebSocket.instances[0]._open());
    await waitFor(() => expect(getByTestId("status").textContent).toBe("connected"));
  });

  it("invalidates the agents query key when an agent_spawn event arrives", async () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    render(
      <QueryClientProvider client={qc}>
        <WebSocketProvider><StatusProbe /></WebSocketProvider>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => {
      FakeWebSocket.instances[0]._open();
      FakeWebSocket.instances[0]._msg({ type: "agent_spawn", agent_id: "a-1" });
    });
    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith({ queryKey: ["agents"] });
    });
  });

  it("transitions to 'reconnecting' status on close and opens a new socket", async () => {
    vi.useFakeTimers();
    try {
      const qc = new QueryClient();
      const { getByTestId } = render(
        <QueryClientProvider client={qc}>
          <WebSocketProvider><StatusProbe /></WebSocketProvider>
        </QueryClientProvider>,
      );
      await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
      act(() => FakeWebSocket.instances[0]._open());
      await waitFor(() => expect(getByTestId("status").textContent).toBe("connected"));

      act(() => FakeWebSocket.instances[0]._disconnect());
      await waitFor(() => expect(getByTestId("status").textContent).toBe("reconnecting"));

      // Backoff: first retry after ~1s
      act(() => { vi.advanceTimersByTime(1100); });
      await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
    } finally {
      vi.useRealTimers();
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web && npm test -- ws.test.tsx
```

Expected: FAIL — `src/ws/invalidator.ts` and `src/ws/provider.tsx` do not exist.

- [ ] **Step 3: Implement invalidator + provider**

`web/src/ws/invalidator.ts`:

```ts
import type { QueryKey } from "@tanstack/react-query";

// event_type → list of query keys to invalidate when this event fires.
// Single source of truth; tests pin every event type from spec §5.2.
export const INVALIDATOR: Record<string, QueryKey[]> = {
  agent_spawn: [["agents"]],
  agent_progress: [["agents"]],
  agent_complete: [["agents"], ["cost"]],
  agent_failed: [["agents"], ["cost"]],
  cost_update: [["cost"]],
  team_created: [["teams"]],
  task_scheduled: [["tasks"]],
  task_cancelled: [["tasks"]],
};

export function keysFor(eventType: string): QueryKey[] {
  return INVALIDATOR[eventType] ?? [];
}
```

`web/src/ws/provider.tsx`:

```tsx
import React, {
  createContext, useContext, useEffect, useRef, useState,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { keysFor } from "./invalidator";

export type WsStatus = "connecting" | "connected" | "reconnecting";

interface WsEvent {
  type: string;
  [k: string]: unknown;
}

const StatusContext = createContext<WsStatus>("connecting");
const EventsContext = createContext<{ subscribe: (cb: (e: WsEvent) => void) => () => void }>(
  { subscribe: () => () => undefined },
);

export function useWebSocketStatus(): WsStatus {
  return useContext(StatusContext);
}

export function useWebSocketEvents(cb: (e: WsEvent) => void): void {
  const ctx = useContext(EventsContext);
  useEffect(() => ctx.subscribe(cb), [ctx, cb]);
}

const BACKOFF_SCHEDULE_MS = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000] as const;

function wsUrl(): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}/ws`;
}

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const [status, setStatus] = useState<WsStatus>("connecting");
  const socketRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const subscribersRef = useRef<Set<(e: WsEvent) => void>>(new Set());

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      if (cancelled) return;
      const ws = new WebSocket(wsUrl());
      socketRef.current = ws;

      ws.onopen = () => {
        if (cancelled) return;
        retryRef.current = 0;
        setStatus("connected");
      };

      ws.onmessage = (ev) => {
        let parsed: WsEvent | null = null;
        try { parsed = JSON.parse(ev.data) as WsEvent; } catch { return; }
        if (!parsed || typeof parsed.type !== "string") return;
        for (const key of keysFor(parsed.type)) {
          qc.invalidateQueries({ queryKey: key });
        }
        for (const sub of subscribersRef.current) sub(parsed);
      };

      ws.onclose = () => {
        if (cancelled) return;
        socketRef.current = null;
        setStatus("reconnecting");
        const idx = Math.min(retryRef.current, BACKOFF_SCHEDULE_MS.length - 1);
        const delay = BACKOFF_SCHEDULE_MS[idx];
        retryRef.current += 1;
        timer = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        // The browser will follow up with onclose; nothing to do here besides log.
        // eslint-disable-next-line no-console
        console.warn("WebSocket error");
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      socketRef.current?.close();
    };
  }, [qc]);

  const eventsApi = useRef({
    subscribe(cb: (e: WsEvent) => void): () => void {
      subscribersRef.current.add(cb);
      return () => subscribersRef.current.delete(cb);
    },
  }).current;

  return (
    <StatusContext.Provider value={status}>
      <EventsContext.Provider value={eventsApi}>
        {children}
      </EventsContext.Provider>
    </StatusContext.Provider>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd web && npm test -- ws.test.tsx
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add web/src/ws web/tests/ws.test.tsx
git commit -m "feat(web): WebSocketProvider with auto-reconnect + event invalidator"
```

---

### Task 5: AgentsPanel + AgentDetailDrawer

**Files:**
- Create: `web/src/components/ui/card.tsx`, `web/src/components/ui/badge.tsx`, `web/src/components/ui/skeleton.tsx`, `web/src/components/ui/button.tsx`, `web/src/components/ui/drawer.tsx`
- Create: `web/src/panels/AgentsPanel.tsx`, `web/src/panels/AgentDetailDrawer.tsx`
- Create: `web/tests/panels/AgentsPanel.test.tsx`

shadcn primitives are introduced here because the panel needs Card/Badge/Skeleton/Drawer.

- [ ] **Step 1: Write the failing test**

`web/tests/panels/AgentsPanel.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

import { AgentsPanel } from "../../src/panels/AgentsPanel";

const ORIGINAL_FETCH = globalThis.fetch;

function wrap(qc?: QueryClient) {
  const c = qc ?? new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: c }, children);
}

const SAMPLE = {
  agents: [
    {
      agent_id: "a-1", name: "backend-dev", role: "executor", tier: "standard",
      state: "running", task: "Implement endpoints", tools: ["read_file"], skills: [],
      iteration: 3, cost_cents: 12.4, retry_count: 0,
      created_at: "2026-05-17T14:02:11Z",
      last_heartbeat: "2026-05-17T14:05:42Z",
      finished_at: null,
    },
  ],
};

describe("AgentsPanel", () => {
  beforeEach(() => { globalThis.fetch = vi.fn() as unknown as typeof fetch; });
  afterEach(() => { globalThis.fetch = ORIGINAL_FETCH; });

  it("renders the agent list", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify(SAMPLE), { status: 200 }),
    );
    render(<AgentsPanel />, { wrapper: wrap() });
    await waitFor(() => expect(screen.getByText("backend-dev")).toBeInTheDocument());
    expect(screen.getByText(/running/i)).toBeInTheDocument();
  });

  it("renders 'No active sub-agents' on empty list (spec §4.8)", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ agents: [] }), { status: 200 }),
    );
    render(<AgentsPanel />, { wrapper: wrap() });
    await waitFor(() => expect(screen.getByText(/No active sub-agents/i)).toBeInTheDocument());
  });

  it("renders an error card with the envelope message on 5xx", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(
        JSON.stringify({ error: { message: "broken", type: "internal_error", code: "x" } }),
        { status: 500 },
      ),
    );
    render(<AgentsPanel />, { wrapper: wrap() });
    await waitFor(() => expect(screen.getByText(/broken/)).toBeInTheDocument());
  });

  it("opens the detail drawer when an agent row is clicked", async () => {
    const fetchMock = vi.fn();
    (globalThis.fetch as unknown) = fetchMock;
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(SAMPLE), { status: 200 }));
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      ...SAMPLE.agents[0], error: null,
    }), { status: 200 }));

    render(<AgentsPanel />, { wrapper: wrap() });
    await waitFor(() => expect(screen.getByText("backend-dev")).toBeInTheDocument());
    await userEvent.click(screen.getByText("backend-dev"));
    await waitFor(() =>
      expect(screen.getByRole("dialog")).toBeInTheDocument()
    );
    expect(screen.getByRole("dialog")).toHaveTextContent("Implement endpoints");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web && npm test -- panels/AgentsPanel
```

Expected: FAIL — the panel and shadcn primitives don't exist.

- [ ] **Step 3: Implement shadcn primitives + the panel**

`web/src/components/ui/card.tsx`:

```tsx
import { cn } from "@/lib/cn";
import type { HTMLAttributes } from "react";

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-lg border bg-background p-4", className)} {...rest} />;
}
export function CardHeader({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("flex items-center justify-between mb-3", className)} {...rest} />;
}
export function CardTitle({ className, ...rest }: HTMLAttributes<HTMLHeadingElement>) {
  return <h3 className={cn("text-sm font-semibold uppercase tracking-wide", className)} {...rest} />;
}
export function CardBody({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("space-y-2", className)} {...rest} />;
}
```

`web/src/components/ui/badge.tsx`:

```tsx
import { cn } from "@/lib/cn";
import type { HTMLAttributes } from "react";

type Variant = "default" | "success" | "warning" | "danger" | "muted";

const VARIANT: Record<Variant, string> = {
  default: "bg-accent text-foreground",
  success: "bg-green-500/15 text-green-700 dark:text-green-300",
  warning: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  danger: "bg-red-500/15 text-red-700 dark:text-red-300",
  muted: "bg-muted text-muted-foreground",
};

export function Badge({
  className, variant = "default", ...rest
}: HTMLAttributes<HTMLSpanElement> & { variant?: Variant }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-2 py-0.5 text-xs font-medium",
        VARIANT[variant], className,
      )}
      {...rest}
    />
  );
}
```

`web/src/components/ui/skeleton.tsx`:

```tsx
import { cn } from "@/lib/cn";
import type { HTMLAttributes } from "react";

export function Skeleton({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("animate-pulse bg-muted rounded h-4", className)} {...rest} />;
}
```

`web/src/components/ui/button.tsx`:

```tsx
import { cn } from "@/lib/cn";
import type { ButtonHTMLAttributes } from "react";

export function Button({ className, ...rest }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded border border-border px-3 py-1 text-sm hover:bg-accent transition-colors",
        className,
      )}
      {...rest}
    />
  );
}
```

`web/src/components/ui/drawer.tsx` — minimal accessible drawer (no external dep):

```tsx
import { useEffect } from "react";
import { cn } from "@/lib/cn";

export function Drawer({
  open, onClose, children, className,
}: {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  className?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <>
      <div
        aria-hidden="true"
        className="fixed inset-0 bg-black/30 z-40"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        className={cn(
          "fixed right-0 top-0 h-full w-[420px] max-w-[100vw] bg-background border-l border-border z-50 p-6 overflow-y-auto shadow-xl",
          className,
        )}
      >
        {children}
      </div>
    </>
  );
}
```

`web/src/panels/AgentDetailDrawer.tsx`:

```tsx
import { useAgentDetail } from "@/api/agents";
import { Drawer } from "@/components/ui/drawer";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

export function AgentDetailDrawer({
  agentId, onClose,
}: { agentId: string | null; onClose: () => void }) {
  const q = useAgentDetail(agentId);

  return (
    <Drawer open={agentId !== null} onClose={onClose}>
      <h2 className="text-lg font-semibold mb-4">Agent detail</h2>
      {q.isLoading && <Skeleton className="h-32" />}
      {q.isError && <p className="text-red-600">{q.error.message}</p>}
      {q.isSuccess && q.data && (
        <div className="space-y-3 text-sm">
          <div><span className="text-muted-foreground">ID</span><br /><code>{q.data.agent_id}</code></div>
          <div><span className="text-muted-foreground">Name</span><br />{q.data.name}</div>
          <div>
            <span className="text-muted-foreground">State</span><br />
            <Badge variant={badgeVariantFor(q.data.state)}>{q.data.state}</Badge>
          </div>
          <div>
            <span className="text-muted-foreground">Role · Tier</span><br />
            {q.data.role} · {q.data.tier}
          </div>
          <div>
            <span className="text-muted-foreground">Task</span><br />
            <pre className="whitespace-pre-wrap text-xs">{q.data.task}</pre>
          </div>
          {q.data.error && (
            <div>
              <span className="text-muted-foreground">Last error</span><br />
              <pre className="whitespace-pre-wrap text-xs text-red-600">{q.data.error}</pre>
            </div>
          )}
        </div>
      )}
    </Drawer>
  );
}

function badgeVariantFor(state: string) {
  if (state === "running") return "success";
  if (state === "failed") return "danger";
  if (state === "blocked") return "warning";
  return "muted";
}
```

`web/src/panels/AgentsPanel.tsx`:

```tsx
import { useState } from "react";
import { useAgents } from "@/api/agents";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { AgentDetailDrawer } from "./AgentDetailDrawer";
import type { AgentState } from "@/api/types";

export function AgentsPanel() {
  const q = useAgents();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Agents{q.data ? ` (${q.data.agents.length})` : ""}</CardTitle>
      </CardHeader>
      <CardBody>
        {q.isLoading && <Skeleton className="h-16" />}
        {q.isError && (
          <div className="space-y-2">
            <p className="text-red-600 text-sm">{q.error.message}</p>
            <Button onClick={() => q.refetch()}>Retry</Button>
          </div>
        )}
        {q.isSuccess && q.data.agents.length === 0 && (
          <p className="text-muted-foreground text-sm">No active sub-agents.</p>
        )}
        {q.isSuccess && q.data.agents.length > 0 && (
          <ul className="divide-y divide-border">
            {q.data.agents.map((a) => (
              <li key={a.agent_id}>
                <button
                  type="button"
                  className="w-full text-left py-2 hover:bg-accent rounded px-2 flex items-center justify-between"
                  onClick={() => setSelectedId(a.agent_id)}
                >
                  <span className="font-medium">{a.name}</span>
                  <span className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Badge variant={badgeFor(a.state)}>{a.state}</Badge>
                    <span>iter {a.iteration}</span>
                    <span>${(a.cost_cents / 100).toFixed(2)}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
      <AgentDetailDrawer
        agentId={selectedId}
        onClose={() => setSelectedId(null)}
      />
    </Card>
  );
}

function badgeFor(s: AgentState) {
  if (s === "running") return "success" as const;
  if (s === "failed") return "danger" as const;
  if (s === "blocked") return "warning" as const;
  return "muted" as const;
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd web && npm test -- panels/AgentsPanel
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/ui web/src/panels/AgentsPanel.tsx web/src/panels/AgentDetailDrawer.tsx web/tests/panels/AgentsPanel.test.tsx
git commit -m "feat(web): AgentsPanel + detail drawer with shadcn primitives"
```

---

### Task 6: TeamsPanel

**Files:**
- Create: `web/src/panels/TeamsPanel.tsx`
- Create: `web/tests/panels/TeamsPanel.test.tsx`

- [ ] **Step 1: Write the failing test**

`web/tests/panels/TeamsPanel.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";

import { TeamsPanel } from "../../src/panels/TeamsPanel";

const ORIGINAL_FETCH = globalThis.fetch;

function wrap() {
  const c = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: c }, children);
}

describe("TeamsPanel", () => {
  beforeEach(() => { globalThis.fetch = vi.fn() as unknown as typeof fetch; });
  afterEach(() => { globalThis.fetch = ORIGINAL_FETCH; });

  it("renders the team list with current phase + agent count", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({
        teams: [
          {
            team_id: "team-7e2c1a89",
            phases: ["plan", "execute", "verify"],
            current_phase: "execute",
            is_finished: false,
            agent_count: 3,
            agent_ids: ["a", "b", "c"],
          },
        ],
      }), { status: 200 }),
    );
    render(<TeamsPanel />, { wrapper: wrap() });
    await waitFor(() => expect(screen.getByText(/team-7e2c1a89/)).toBeInTheDocument());
    expect(screen.getByText("execute")).toBeInTheDocument();
    expect(screen.getByText(/3 agents/)).toBeInTheDocument();
  });

  it("renders 'no teams' when list is empty", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ teams: [] }), { status: 200 }),
    );
    render(<TeamsPanel />, { wrapper: wrap() });
    await waitFor(() => expect(screen.getByText(/No active teams/i)).toBeInTheDocument());
  });

  it("renders 'finished' badge for completed teams", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({
        teams: [{
          team_id: "team-done",
          phases: ["plan"],
          current_phase: null,
          is_finished: true,
          agent_count: 1,
          agent_ids: ["a"],
        }],
      }), { status: 200 }),
    );
    render(<TeamsPanel />, { wrapper: wrap() });
    await waitFor(() => expect(screen.getByText(/finished/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web && npm test -- panels/TeamsPanel
```

Expected: FAIL — `TeamsPanel` does not exist.

- [ ] **Step 3: Implement TeamsPanel**

`web/src/panels/TeamsPanel.tsx`:

```tsx
import { useTeams } from "@/api/teams";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";

export function TeamsPanel() {
  const q = useTeams();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Teams{q.data ? ` (${q.data.teams.length})` : ""}</CardTitle>
      </CardHeader>
      <CardBody>
        {q.isLoading && <Skeleton className="h-16" />}
        {q.isError && (
          <div className="space-y-2">
            <p className="text-red-600 text-sm">{q.error.message}</p>
            <Button onClick={() => q.refetch()}>Retry</Button>
          </div>
        )}
        {q.isSuccess && q.data.teams.length === 0 && (
          <p className="text-muted-foreground text-sm">No active teams.</p>
        )}
        {q.isSuccess && q.data.teams.map((t) => (
          <div key={t.team_id} className="text-sm border border-border rounded p-2 space-y-1">
            <div className="flex items-center justify-between">
              <code className="text-xs">{t.team_id}</code>
              {t.is_finished
                ? <Badge variant="muted">finished</Badge>
                : <Badge variant="success">{t.current_phase}</Badge>}
            </div>
            <div className="text-xs text-muted-foreground">
              phases: {t.phases.join(" → ")}
            </div>
            <div className="text-xs text-muted-foreground">
              {t.agent_count} agents
            </div>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd web && npm test -- panels/TeamsPanel
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add web/src/panels/TeamsPanel.tsx web/tests/panels/TeamsPanel.test.tsx
git commit -m "feat(web): TeamsPanel with phase indicator"
```

---

### Task 7: TasksPanel

**Files:**
- Create: `web/src/panels/TasksPanel.tsx`
- Create: `web/tests/panels/TasksPanel.test.tsx`

- [ ] **Step 1: Write the failing test**

`web/tests/panels/TasksPanel.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";

import { TasksPanel } from "../../src/panels/TasksPanel";

const ORIGINAL_FETCH = globalThis.fetch;

function wrap() {
  const c = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: c }, children);
}

describe("TasksPanel", () => {
  beforeEach(() => { globalThis.fetch = vi.fn() as unknown as typeof fetch; });
  afterEach(() => { globalThis.fetch = ORIGINAL_FETCH; });

  it("renders scheduled tasks with schedule + next_run", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({
        tasks: [{
          task_id: "t-1",
          prompt: "Daily standup summary",
          schedule_type: "cron",
          schedule_value: "0 9 * * *",
          model_tier: "standard",
          next_run: "2099-01-01T09:00:00+00:00",
          created_at: "2026-05-17T00:00:00+00:00",
        }],
      }), { status: 200 }),
    );
    render(<TasksPanel />, { wrapper: wrap() });
    await waitFor(() => expect(screen.getByText(/Daily standup summary/)).toBeInTheDocument());
    expect(screen.getByText("cron")).toBeInTheDocument();
    expect(screen.getByText("0 9 * * *")).toBeInTheDocument();
  });

  it("renders 'no tasks' on empty list", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ tasks: [] }), { status: 200 }),
    );
    render(<TasksPanel />, { wrapper: wrap() });
    await waitFor(() => expect(screen.getByText(/No scheduled tasks/i)).toBeInTheDocument());
  });

  it("renders '—' for next_run when null", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({
        tasks: [{
          task_id: "t-1", prompt: "x", schedule_type: "once",
          schedule_value: "2099-01-01T00:00:00+00:00",
          model_tier: null, next_run: null,
          created_at: "2026-05-17T00:00:00+00:00",
        }],
      }), { status: 200 }),
    );
    render(<TasksPanel />, { wrapper: wrap() });
    await waitFor(() => expect(screen.getByText("—")).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web && npm test -- panels/TasksPanel
```

Expected: FAIL.

- [ ] **Step 3: Implement TasksPanel**

`web/src/panels/TasksPanel.tsx`:

```tsx
import { useTasks } from "@/api/tasks";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";

export function TasksPanel() {
  const q = useTasks();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Tasks{q.data ? ` (${q.data.tasks.length})` : ""}</CardTitle>
      </CardHeader>
      <CardBody>
        {q.isLoading && <Skeleton className="h-16" />}
        {q.isError && (
          <div className="space-y-2">
            <p className="text-red-600 text-sm">{q.error.message}</p>
            <Button onClick={() => q.refetch()}>Retry</Button>
          </div>
        )}
        {q.isSuccess && q.data.tasks.length === 0 && (
          <p className="text-muted-foreground text-sm">No scheduled tasks.</p>
        )}
        {q.isSuccess && q.data.tasks.length > 0 && (
          <ul className="space-y-1 text-sm">
            {q.data.tasks.map((t) => (
              <li key={t.task_id} className="border border-border rounded p-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium truncate">{t.prompt}</span>
                  <Badge variant="muted">{t.schedule_type}</Badge>
                </div>
                <div className="text-xs text-muted-foreground mt-1 flex items-center gap-3">
                  <code>{t.schedule_value}</code>
                  <span>next: {t.next_run ?? "—"}</span>
                  {t.model_tier && <span>tier: {t.model_tier}</span>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd web && npm test -- panels/TasksPanel
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add web/src/panels/TasksPanel.tsx web/tests/panels/TasksPanel.test.tsx
git commit -m "feat(web): TasksPanel with cron-format display"
```

---

### Task 8: CostPanel (Recharts line chart)

**Files:**
- Create: `web/src/panels/CostPanel.tsx`
- Create: `web/tests/panels/CostPanel.test.tsx`

For v1, Cost panel renders a horizontal bar chart over the `by_tier` breakdown (simplest meaningful visualization given `/v1/cost/breakdown` returns aggregates, not a time series). A future iteration can add `/v1/cost/timeseries` and a true line chart.

- [ ] **Step 1: Write the failing test**

`web/tests/panels/CostPanel.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";

// Recharts renders SVG that's hard to assert on in jsdom; stub it.
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) =>
    React.createElement("div", { "data-testid": "responsive" }, children),
  BarChart: ({ children, data }: { children: React.ReactNode; data: unknown }) =>
    React.createElement(
      "div",
      { "data-testid": "barchart", "data-rows": JSON.stringify(data) },
      children,
    ),
  Bar: () => React.createElement("div", { "data-testid": "bar" }),
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  CartesianGrid: () => null,
}));

import { CostPanel } from "../../src/panels/CostPanel";

const ORIGINAL_FETCH = globalThis.fetch;

function wrap() {
  const c = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: c }, children);
}

describe("CostPanel", () => {
  beforeEach(() => { globalThis.fetch = vi.fn() as unknown as typeof fetch; });
  afterEach(() => { globalThis.fetch = ORIGINAL_FETCH; });

  it("renders the bar chart with by_tier breakdown rows", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({
        by_user: { u1: 0.12 },
        by_tier: { standard: 0.34, advanced: 0.78 },
        by_agent: { "agent-a": 0.50 },
      }), { status: 200 }),
    );
    render(<CostPanel />, { wrapper: wrap() });
    await waitFor(() => expect(screen.getByTestId("barchart")).toBeInTheDocument());
    const rows = JSON.parse(screen.getByTestId("barchart").getAttribute("data-rows")!);
    expect(rows).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ tier: "standard", cost_cents: 0.34 }),
        expect.objectContaining({ tier: "advanced", cost_cents: 0.78 }),
      ]),
    );
  });

  it("renders 'no cost data' when by_tier is empty", async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ by_user: {}, by_tier: {}, by_agent: {} }), { status: 200 }),
    );
    render(<CostPanel />, { wrapper: wrap() });
    await waitFor(() => expect(screen.getByText(/No cost data yet/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web && npm test -- panels/CostPanel
```

Expected: FAIL.

- [ ] **Step 3: Implement CostPanel**

`web/src/panels/CostPanel.tsx`:

```tsx
import { useCostBreakdown } from "@/api/cost";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer,
} from "recharts";

export function CostPanel() {
  const q = useCostBreakdown();

  const rows = q.data
    ? Object.entries(q.data.by_tier).map(([tier, cost_cents]) => ({ tier, cost_cents }))
    : [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Cost by tier</CardTitle>
      </CardHeader>
      <CardBody>
        {q.isLoading && <Skeleton className="h-32" />}
        {q.isError && (
          <div className="space-y-2">
            <p className="text-red-600 text-sm">{q.error.message}</p>
            <Button onClick={() => q.refetch()}>Retry</Button>
          </div>
        )}
        {q.isSuccess && rows.length === 0 && (
          <p className="text-muted-foreground text-sm">No cost data yet.</p>
        )}
        {q.isSuccess && rows.length > 0 && (
          <div style={{ width: "100%", height: 220 }}>
            <ResponsiveContainer>
              <BarChart data={rows} layout="vertical" margin={{ left: 24 }}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" dataKey="cost_cents" />
                <YAxis type="category" dataKey="tier" />
                <Tooltip />
                <Bar dataKey="cost_cents" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd web && npm test -- panels/CostPanel
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add web/src/panels/CostPanel.tsx web/tests/panels/CostPanel.test.tsx
git commit -m "feat(web): CostPanel — by-tier bar chart over /v1/cost/breakdown"
```

---

### Task 9: LiveEventsPanel — ring buffer + reconnect banner

**Files:**
- Create: `web/src/panels/LiveEventsPanel.tsx`
- Create: `web/tests/panels/LiveEventsPanel.test.tsx`

- [ ] **Step 1: Write the failing test**

`web/tests/panels/LiveEventsPanel.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, act } from "@testing-library/react";
import React from "react";

import { LiveEventsPanel } from "../../src/panels/LiveEventsPanel";

// Stub the ws module so we don't need a real WebSocket.
let pushedEvent: ((e: unknown) => void) | null = null;
let mockStatus: "connecting" | "connected" | "reconnecting" = "connecting";

vi.mock("../../src/ws/provider", async () => {
  return {
    useWebSocketStatus: () => mockStatus,
    useWebSocketEvents: (cb: (e: unknown) => void) => {
      pushedEvent = cb;
      // simulate one synchronous mount-time event delivery
    },
  };
});

function wrap() {
  const c = new QueryClient();
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: c }, children);
}

describe("LiveEventsPanel", () => {
  it("renders pushed events in newest-first order", () => {
    render(<LiveEventsPanel />, { wrapper: wrap() });
    act(() => {
      pushedEvent?.({ type: "agent_spawn", agent_id: "a-1" });
      pushedEvent?.({ type: "agent_complete", agent_id: "a-1" });
    });
    const items = screen.getAllByTestId("event-row");
    expect(items).toHaveLength(2);
    // Newest first
    expect(items[0]).toHaveTextContent("agent_complete");
    expect(items[1]).toHaveTextContent("agent_spawn");
  });

  it("caps the buffer at 50 entries (FIFO eviction)", () => {
    render(<LiveEventsPanel />, { wrapper: wrap() });
    act(() => {
      for (let i = 0; i < 60; i++) {
        pushedEvent?.({ type: `event_${i}` });
      }
    });
    const items = screen.getAllByTestId("event-row");
    expect(items.length).toBe(50);
    expect(items[0]).toHaveTextContent("event_59");
    expect(items[items.length - 1]).toHaveTextContent("event_10");
  });

  it("shows a reconnecting banner when status is reconnecting", () => {
    mockStatus = "reconnecting";
    render(<LiveEventsPanel />, { wrapper: wrap() });
    expect(screen.getByText(/reconnecting/i)).toBeInTheDocument();
    mockStatus = "connecting";
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web && npm test -- panels/LiveEventsPanel
```

Expected: FAIL.

- [ ] **Step 3: Implement LiveEventsPanel**

`web/src/panels/LiveEventsPanel.tsx`:

```tsx
import { useState } from "react";
import { Card, CardHeader, CardTitle, CardBody } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useWebSocketEvents, useWebSocketStatus } from "@/ws/provider";

const BUFFER_LIMIT = 50;

interface BufferedEvent {
  id: number;
  receivedAt: number;
  type: string;
  raw: unknown;
}

export function LiveEventsPanel() {
  const [buffer, setBuffer] = useState<BufferedEvent[]>([]);
  const status = useWebSocketStatus();

  useWebSocketEvents((ev) => {
    setBuffer((prev) => {
      const next: BufferedEvent[] = [
        {
          id: prev.length > 0 ? prev[0].id + 1 : 1,
          receivedAt: Date.now(),
          type: (ev as { type?: string }).type ?? "unknown",
          raw: ev,
        },
        ...prev,
      ];
      // Cap to BUFFER_LIMIT, newest first.
      return next.slice(0, BUFFER_LIMIT);
    });
  });

  return (
    <Card className="h-full flex flex-col">
      <CardHeader>
        <CardTitle>Live events</CardTitle>
        {status === "reconnecting" && (
          <Badge variant="warning">reconnecting…</Badge>
        )}
        {status === "connecting" && (
          <Badge variant="muted">connecting…</Badge>
        )}
      </CardHeader>
      <CardBody className="overflow-y-auto flex-1 font-mono text-xs">
        {buffer.length === 0 && (
          <p className="text-muted-foreground">Waiting for events…</p>
        )}
        {buffer.map((e) => (
          <div key={e.id} data-testid="event-row" className="py-0.5">
            <span className="text-muted-foreground">
              {new Date(e.receivedAt).toLocaleTimeString()}
            </span>{" "}
            <span>{e.type}</span>
          </div>
        ))}
      </CardBody>
    </Card>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd web && npm test -- panels/LiveEventsPanel
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add web/src/panels/LiveEventsPanel.tsx web/tests/panels/LiveEventsPanel.test.tsx
git commit -m "feat(web): LiveEventsPanel with 50-entry ring buffer + reconnect banner"
```

---

### Task 10: App shell — 2×2 grid + right rail layout

**Files:**
- Modify: `web/src/App.tsx` — replace scaffold with the layout from spec §4.3
- Modify: `web/src/main.tsx` — wrap with `QueryClientProvider` + `WebSocketProvider`
- Create: `web/tests/App.layout.test.tsx`

- [ ] **Step 1: Write the failing test**

Replace `web/tests/App.test.tsx` contents with the layout test (rename to `App.layout.test.tsx`):

```tsx
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";

// Stub WebSocket so the provider doesn't actually connect.
class NoopWebSocket {
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  close() { /* no-op */ }
  constructor(_url: string) { /* no-op */ }
}

import App from "../src/App";
import { WebSocketProvider } from "../src/ws/provider";

const ORIGINAL_FETCH = globalThis.fetch;

function wrap() {
  const c = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(
      QueryClientProvider,
      { client: c },
      React.createElement(WebSocketProvider, null, children),
    );
}

describe("App shell", () => {
  beforeEach(() => {
    // @ts-expect-error overriding global for the test
    globalThis.WebSocket = NoopWebSocket;
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ agents: [], teams: [], tasks: [],
        by_user: {}, by_tier: {}, by_agent: {} }), { status: 200 }),
    ) as unknown as typeof fetch;
  });
  afterEach(() => { globalThis.fetch = ORIGINAL_FETCH; });

  it("renders the title and all five panel headers", async () => {
    render(<App />, { wrapper: wrap() });
    await waitFor(() => expect(screen.getByText(/LangAgent Dashboard/i)).toBeInTheDocument());
    // The five panel titles should all be present at first paint
    expect(screen.getByText(/^Agents/i)).toBeInTheDocument();
    expect(screen.getByText(/^Teams/i)).toBeInTheDocument();
    expect(screen.getByText(/^Tasks/i)).toBeInTheDocument();
    expect(screen.getByText(/Cost by tier/i)).toBeInTheDocument();
    expect(screen.getByText(/Live events/i)).toBeInTheDocument();
  });
});
```

Delete the older `web/tests/App.test.tsx` if it still exists (the title-only test is subsumed by `App.layout.test.tsx`).

- [ ] **Step 2: Run test to verify it fails**

```bash
cd web && npm test -- App.layout
```

Expected: FAIL — App still renders the scaffolding placeholder; doesn't mount the panels.

- [ ] **Step 3: Implement the layout**

Replace `web/src/App.tsx`:

```tsx
import { AgentsPanel } from "@/panels/AgentsPanel";
import { TeamsPanel } from "@/panels/TeamsPanel";
import { TasksPanel } from "@/panels/TasksPanel";
import { CostPanel } from "@/panels/CostPanel";
import { LiveEventsPanel } from "@/panels/LiveEventsPanel";

export default function App() {
  return (
    <main className="min-h-screen p-4 grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-4">
      <div>
        <header className="mb-4">
          <h1 className="text-xl font-semibold">LangAgent Dashboard</h1>
          <p className="text-xs text-muted-foreground">v1 · localhost</p>
        </header>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <AgentsPanel />
          <TeamsPanel />
          <TasksPanel />
          <CostPanel />
        </div>
      </div>
      <aside className="lg:sticky lg:top-4 self-start h-[calc(100vh-2rem)]">
        <LiveEventsPanel />
      </aside>
    </main>
  );
}
```

Replace `web/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import { WebSocketProvider } from "./ws/provider";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, refetchOnWindowFocus: false },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <WebSocketProvider>
        <App />
      </WebSocketProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd web && npm test
```

Expected: ALL passes (every previous test still green; the new layout test passes).

- [ ] **Step 5: Commit**

```bash
git add web/src/App.tsx web/src/main.tsx web/tests
git commit -m "feat(web): App shell — 2×2 grid + right-rail live events"
```

---

### Task 11: Production build wiring — `main.py` passes `web_dist_path`

**Files:**
- Modify: `src/main.py` — pass `web_dist_path` to `APIChannel` when `src/api/static/` exists
- Create: `tests/test_main_static_path.py`

- [ ] **Step 1: Write the failing test**

`tests/test_main_static_path.py`:

```python
"""Test that main.py wires web_dist_path into APIChannel iff the dist directory exists."""
from pathlib import Path


def test_apichannel_static_path_referenced_in_main():
    """main.py must reference src/api/static for the web_dist_path arg.

    Structural test (not running main()) — confirms the wiring stays
    discoverable by code search if a future refactor moves the channel
    construction.
    """
    main_src = Path("src/main.py").read_text()
    assert "web_dist_path" in main_src, (
        "src/main.py must pass web_dist_path into APIChannel when serving the Web UI"
    )
    # The path should resolve to src/api/static
    assert "api" in main_src and "static" in main_src


def test_apichannel_accepts_none_web_dist_path():
    """APIChannel must accept web_dist_path=None (the default for older callers)."""
    from src.channels.api import APIChannel
    ch = APIChannel(host="127.0.0.1", port=0, web_dist_path=None)
    assert ch._web_dist_path is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_main_static_path.py -v
```

Expected: FAIL — `web_dist_path` not yet referenced in `src/main.py`.

- [ ] **Step 3: Wire main.py**

In `src/main.py`, locate the `if config.channels.api.enabled:` block. Just before the `APIChannel(...)` construction, compute the dist path. Update the construction to include `web_dist_path`:

```python
        from pathlib import Path as _Path
        _api_static = _Path(__file__).parent / "api" / "static"
        _web_dist_path = str(_api_static) if _api_static.is_dir() else None
        if _web_dist_path:
            logger.info("Web UI bundle found at %s — serving at /web/", _web_dist_path)

        api = APIChannel(
            host=api_config.host,
            port=api_config.port,
            workspace=config.agent.workspace,
            cost_tracker=bundle.cost_tracker,
            event_hub=event_hub,
            subagent_registry=bundle.subagent_registry,
            swarm=bundle.swarm,
            config=config,
            web_dist_path=_web_dist_path,
        )
```

- [ ] **Step 4: Run tests + full regression**

```bash
pytest tests/test_main_static_path.py -v
pytest tests/ -q --tb=line --ignore=tests/test_middleware_bridge.py --ignore=tests/test_middleware_full.py 2>&1 | tail -5
```

Expected: 2 new tests pass; full Python suite remains at the 6-pre-existing baseline.

- [ ] **Step 5: Build the bundle and smoke-test it end-to-end**

```bash
cd web && npm run build
cd ..
ls src/api/static/index.html  # must exist
ls src/api/static/assets/     # must contain JS + CSS
```

Then manually:

```bash
python -m src.main &
SERVER_PID=$!
sleep 3
curl -s -I http://127.0.0.1:8900/ | head -1     # 302 → /web/
curl -s -I http://127.0.0.1:8900/web/ | head -1 # 200
curl -s http://127.0.0.1:8900/web/ | grep -q "LangAgent Dashboard" && echo "dashboard served OK"
kill $SERVER_PID
```

Expected: 302 on `/`, 200 on `/web/`, "dashboard served OK".

- [ ] **Step 6: Commit**

```bash
git add src/main.py tests/test_main_static_path.py
git commit -m "feat: serve Vite dashboard bundle from src/api/static via APIChannel"
```

---

### Task 12: Final verification + tag `v0.6.0-phase2b-ii`

**Files:**
- Modify: `docs/superpowers/plans/README.md`

Verification-only. No code changes; runs end-to-end smoke checks, updates the plan index, tags, pushes.

- [ ] **Step 1: Run full Python test suite**

```bash
pytest tests/ -q --tb=line --ignore=tests/test_middleware_bridge.py --ignore=tests/test_middleware_full.py 2>&1 | tail -5
```

Expected: 6 pre-existing failures (cc_handler, gateway_server_handler, router_extended). All other tests pass. Total passes ≈ 877 (870 baseline + ~7 added by T2+T11).

- [ ] **Step 2: Run full Vitest suite**

```bash
cd web && npm test
```

Expected: ≥20 tests pass, 0 fail.

- [ ] **Step 3: Verify production build still works**

```bash
cd web && npm run build && ls ../src/api/static/index.html
```

Expected: `../src/api/static/index.html` exists.

- [ ] **Step 4: Update plan index**

In `docs/superpowers/plans/README.md`, update the Phase 2B-II row:

```markdown
| [Phase 2B-II](2026-05-17-phase2b-ii-web-ui.md) | Web UI v1 | **DONE** (v0.6.0-phase2b-ii) | Dashboard-only MVP: 5 panels (Agents, Teams, Tasks, Cost, Live Events) | Phase 2B-I |
```

- [ ] **Step 5: Tag, commit README, push**

```bash
git add docs/superpowers/plans/README.md
git commit -m "docs: mark Phase 2B-II as DONE (v0.6.0-phase2b-ii)"
git tag v0.6.0-phase2b-ii
git push origin feature/implementation-plans
git push origin v0.6.0-phase2b-ii
```

Expected: clean push, tag visible on remote.

---

## Exit Criteria

- [ ] `web/` scaffolded with Vite + React + TS + Tailwind + Vitest
- [ ] `APIChannel` accepts `web_dist_path`; `/` redirects to `/web/`; `/web/*` serves the bundle
- [ ] API client + types + hooks for all five endpoints
- [ ] WebSocketProvider with auto-reconnect (1s/2s/4s/8s/16s/30s backoff)
- [ ] AgentsPanel + detail drawer working
- [ ] TeamsPanel with phase indicator
- [ ] TasksPanel with cron-format display
- [ ] CostPanel with by-tier bar chart
- [ ] LiveEventsPanel with 50-entry ring buffer + reconnect banner
- [ ] App shell: 2×2 grid + right-rail live events
- [ ] `main.py` passes `web_dist_path` when the dist directory exists
- [ ] Full Python suite at the 6-pre-existing-fail baseline
- [ ] Vitest suite ≥20 tests, all green
- [ ] Tag `v0.6.0-phase2b-ii` pushed
- [ ] Plan README updated

---

## What's deferred

- Chat panel — chat already works in Telegram/CLI/API; a 4th surface is duplicate effort. Phase 2C if anyone asks.
- Settings page (memory editor, config viewer, dream log) — files are editable directly.
- Task board (Kanban) view — needs new board projection.
- Git activity view — needs new backend plumbing.
- Authentication (JWT, multi-user, RBAC) — Phase 3.
- Storybook — defer until panel count exceeds ~10.
- Playwright e2e — defer until v1 ships and we have a stable feature surface.
- Optimistic updates — Phase 2C if mutation endpoints are added.
