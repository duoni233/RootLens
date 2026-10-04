import { AlertTriangle, Clock3, GitBranch, ListTree } from "lucide-react";
import type { DiagnosisTrace, TraceStep } from "../lib/types";
import { displayStatus, formatDate } from "../lib/format";
import { StatusBadge } from "./StatusBadge";

const names: Record<string, string> = {
  intent_recognition: "意图识别",
  query_logs: "日志查询",
  query_metrics: "指标查询",
  query_deployments: "发布查询",
  rag_rewrite: "查询改写",
  rag_retrieval: "知识检索",
  rag_rerank: "知识重排",
  routing: "领域路由",
  agent_execution: "Agent 执行",
  evidence_gate: "取证判断",
  query_context: "查询范围",
  diagnosis_assembly: "结构化组装",
};

function overlaps(step: TraceStep, others: TraceStep[]): boolean {
  const start = new Date(step.started_at).getTime();
  const end = new Date(step.completed_at).getTime();
  return others.some(
    (other) =>
      other.step_id !== step.step_id &&
      start < new Date(other.completed_at).getTime() &&
      end > new Date(other.started_at).getTime(),
  );
}

export function TraceTimeline({ trace }: { trace: DiagnosisTrace }) {
  const steps = [...trace.steps].sort(
    (a, b) =>
      new Date(a.started_at).getTime() - new Date(b.started_at).getTime(),
  );
  const origin = new Date(trace.started_at).getTime();
  return (
    <div className="trace-view">
      <div className="trace-header">
        <div>
          <span className="field-label">Trace ID</span>
          <code>{trace.trace_id}</code>
        </div>
        <div>
          <span className="field-label">开始时间</span>
          <strong>{formatDate(trace.started_at)}</strong>
        </div>
        <div>
          <span className="field-label">总体状态</span>
          <StatusBadge status={trace.overall_status || "skipped"} />
        </div>
        <div>
          <span className="field-label">步骤</span>
          <strong>{trace.steps.length}</strong>
        </div>
      </div>
      <div className="trace-steps" role="region" aria-label="执行轨迹">
        {steps.map((step) => (
          <article
            className={`trace-step trace-${step.status}`}
            key={step.step_id}
          >
            <div className="trace-time">
              <span>
                +
                {Math.max(
                  0,
                  (new Date(step.started_at).getTime() - origin) / 1000,
                ).toFixed(2)}
                s
              </span>
              <small>{step.latency_ms.toFixed(0)} ms</small>
            </div>
            <div className="trace-step-main">
              <div className="trace-step-title">
                <ListTree size={17} />
                <h3>{names[step.step_type] || step.step_type}</h3>
                <StatusBadge status={step.status} />
                {overlaps(step, steps) && (
                  <span className="parallel-label">
                    <GitBranch size={13} /> 并行
                  </span>
                )}
              </div>
              <div className="trace-step-sub">
                <code>{step.component}</code>
                <span>
                  <Clock3 size={12} /> {formatDate(step.started_at)}
                </span>
                <span>
                  结果：
                  {step.result_kind ? displayStatus(step.result_kind) : "—"}
                </span>
                {step.degraded && <span>降级</span>}
              </div>
              {(step.error_code || step.metadata.fallback === true) && (
                <div className="trace-alert">
                  <AlertTriangle size={14} />
                  {step.error_code && <code>{step.error_code}</code>}
                  {step.metadata.fallback === true && (
                    <span>已触发 fallback</span>
                  )}
                </div>
              )}
              {(step.evidence_ids.length > 0 ||
                step.knowledge_ids.length > 0) && (
                <div className="trace-refs">
                  {step.evidence_ids.length > 0 && (
                    <span>证据 {step.evidence_ids.join(" · ")}</span>
                  )}
                  {step.knowledge_ids.length > 0 && (
                    <span>知识 {step.knowledge_ids.join(" · ")}</span>
                  )}
                </div>
              )}
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
