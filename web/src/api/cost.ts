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
