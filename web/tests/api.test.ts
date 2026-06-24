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
