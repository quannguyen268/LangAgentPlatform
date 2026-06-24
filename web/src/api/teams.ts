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
