export type DiagnosisBuildStatus =
  | "not_run"
  | "success"
  | "validation_failed"
  | "parse_failed"
  | "assembler_failed";
export type ToolStatus = "ok" | "empty" | "failed" | "degraded";
export type TraceStatus = "success" | "failed" | "degraded" | "skipped";

export interface EvidenceRef {
  evidence_id: string;
  source_type: "log" | "metric" | "deployment";
}

export interface KnowledgeRef {
  document_id: string;
  chunk_id: string;
  source_ref: string;
}

export interface IncidentDiagnosis {
  schema_version: "1";
  status: "diagnosis" | "runbook" | "clarification";
  summary: string;
  affected_services: string[];
  environment: string | null;
  intent: string;
  primary_agent: string | null;
  supporting_agents: string[];
  confirmed_findings: { statement: string; evidence_ids: string[] }[];
  hypotheses: {
    statement: string;
    evidence_ids: string[];
    verification_steps: string[];
  }[];
  recommended_actions: {
    action: string;
    reason: string;
    risk_level: "low" | "medium" | "high";
    requires_approval: boolean;
    related_evidence_ids: string[];
  }[];
  evidence_gaps: { description: string; why_needed: string }[];
  evidence_refs: EvidenceRef[];
  knowledge_refs: KnowledgeRef[];
  tool_status: Record<string, ToolStatus>;
  degraded: boolean;
  requires_approval: boolean;
  clarification_required: boolean;
  clarification_question: string | null;
}

export interface ChatRequest {
  message: string;
  user_id?: string;
  conv_id?: string;
  environment?: "demo" | "staging" | "prod";
  anchor_time?: string;
}

export interface ChatResponse {
  conv_id: string;
  response: string;
  intent: string;
  intent_group: string;
  agent_type: string;
  primary_agent: string;
  supporting_agents: string[];
  escalated: boolean;
  latency_ms: number;
  knowledge_used: boolean;
  entities: Record<string, string[]>;
  evidence_ids: string[];
  tool_status: Record<string, ToolStatus>;
  tool_errors: Record<string, string>;
  rag_stage_status: Record<string, string>;
  clarification_required: boolean;
  diagnosis: IncidentDiagnosis | null;
  diagnosis_status: DiagnosisBuildStatus;
  run_id: string | null;
  persistence_status: "saved" | "failed" | "disabled";
}

export interface HistorySummary {
  run_id: string;
  created_at: string;
  service_name: string | null;
  intent: string;
  primary_agent: string | null;
  diagnosis_status: DiagnosisBuildStatus;
  degraded: boolean;
  clarification_required: boolean;
}

export interface HistoryPage {
  items: HistorySummary[];
  limit: number;
  offset: number;
}

export interface HistoryDetail extends HistorySummary {
  schema_version: string;
  trace_id: string | null;
  request_id: string | null;
  conversation_id: string | null;
  completed_at: string;
  original_message: string;
  environment: string | null;
  supporting_agents: string[];
  response_markdown: string;
  trace_status: "success" | "failed" | "degraded" | null;
  diagnosis: IncidentDiagnosis | null;
  evidence_refs: EvidenceRef[];
  knowledge_refs: KnowledgeRef[];
}

export interface TraceStep {
  step_id: string;
  step_type: string;
  component: string;
  status: TraceStatus;
  started_at: string;
  completed_at: string;
  latency_ms: number;
  result_kind: "items" | "empty" | null;
  error_code: string | null;
  degraded: boolean;
  metadata: Record<string, unknown>;
  evidence_ids: string[];
  knowledge_ids: string[];
}

export interface DiagnosisTrace {
  schema_version: "1";
  trace_id: string;
  request_id: string | null;
  started_at: string;
  completed_at: string | null;
  overall_status: "success" | "failed" | "degraded" | null;
  degraded: boolean;
  steps: TraceStep[];
}

export interface HistoryFilters {
  limit: number;
  offset: number;
  service_name?: string;
  diagnosis_status?: DiagnosisBuildStatus | "";
  degraded?: "" | "true" | "false";
  service_missing?: "" | "true" | "false";
  clarification_required?: "" | "true" | "false";
}
