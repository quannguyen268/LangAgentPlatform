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
