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
