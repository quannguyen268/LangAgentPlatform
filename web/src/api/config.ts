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
