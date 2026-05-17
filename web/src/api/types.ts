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
