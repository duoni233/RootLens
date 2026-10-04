import {
  AlertTriangle,
  ArrowUpRight,
  BookOpen,
  CheckCircle2,
  CircleHelp,
  Database,
  FileText,
  ShieldAlert,
} from "lucide-react";
import { Link } from "react-router-dom";
import type {
  DiagnosisBuildStatus,
  EvidenceRef,
  IncidentDiagnosis,
  KnowledgeRef,
  ToolStatus,
} from "../lib/types";
import { StatusBadge } from "./StatusBadge";

export interface DiagnosisViewProps {
  diagnosis: IncidentDiagnosis | null;
  markdown: string;
  diagnosisStatus: DiagnosisBuildStatus;
  intent: string;
  primaryAgent: string | null;
  supportingAgents: string[];
  serviceName: string | null;
  environment: string | null;
  runId: string | null;
  persistenceStatus?: "saved" | "failed" | "disabled";
  degraded: boolean;
  clarificationRequired: boolean;
  evidenceRefs: EvidenceRef[];
  untypedEvidenceIds?: string[];
  knowledgeRefs: KnowledgeRef[];
  toolStatus: Record<string, ToolStatus>;
}

function EmptyLine({ children }: { children: string }) {
  return <p className="empty-line">{children}</p>;
}

export function DiagnosisView(props: DiagnosisViewProps) {
  const d = props.diagnosis;
  const clarification =
    props.clarificationRequired || d?.status === "clarification";
  return (
    <div className="diagnosis-output">
      <section className="result-overview" aria-label="诊断概览">
        <div className="section-heading">
          <h2>诊断概览</h2>
          <StatusBadge
            status={clarification ? "clarification" : props.diagnosisStatus}
          />
        </div>
        <div className="overview-grid">
          <div>
            <span className="field-label">服务</span>
            <strong>{props.serviceName || "待确认"}</strong>
          </div>
          <div>
            <span className="field-label">环境</span>
            <strong>{props.environment || "未指定"}</strong>
          </div>
          <div>
            <span className="field-label">意图</span>
            <strong>{props.intent}</strong>
          </div>
          <div>
            <span className="field-label">主 Agent</span>
            <strong>{props.primaryAgent || "未执行"}</strong>
          </div>
          <div>
            <span className="field-label">辅助 Agent</span>
            <strong>{props.supportingAgents.join("、") || "无"}</strong>
          </div>
          <div>
            <span className="field-label">运行状态</span>
            <StatusBadge
              status={
                props.degraded
                  ? "degraded"
                  : clarification
                    ? "clarification"
                    : props.diagnosisStatus
              }
            />
          </div>
        </div>
        {(props.persistenceStatus || props.runId) && (
          <div className="persistence-row">
            <span>历史记录</span>
            {props.persistenceStatus && (
              <StatusBadge status={props.persistenceStatus} />
            )}
            {props.runId && (
              <Link to={`/history/${props.runId}`} className="inline-link">
                查看记录 <ArrowUpRight size={14} />
              </Link>
            )}
            {props.persistenceStatus === "failed" && (
              <small>诊断已返回，但本次未保存到历史。</small>
            )}
          </div>
        )}
      </section>

      {clarification ? (
        <section className="clarification-block" aria-label="澄清问题">
          <CircleHelp size={23} />
          <div>
            <h2>需要补充信息</h2>
            <p>{d?.clarification_question || props.markdown}</p>
          </div>
        </section>
      ) : d ? (
        <>
          <section className="result-section" aria-label="诊断摘要">
            <div className="section-heading">
              <h2>摘要</h2>
            </div>
            <p className="summary-text">{d.summary}</p>
          </section>
          <div className="result-columns">
            <section className="result-section" aria-label="已确认事实">
              <div className="section-heading">
                <h2>
                  <CheckCircle2 size={18} /> 已确认事实
                </h2>
                <span className="count">{d.confirmed_findings.length}</span>
              </div>
              {d.confirmed_findings.length ? (
                <ul className="finding-list">
                  {d.confirmed_findings.map((item, index) => (
                    <li key={index}>
                      <p>{item.statement}</p>
                      <small>证据 {item.evidence_ids.join(" · ")}</small>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyLine>没有可确认的现场事实。</EmptyLine>
              )}
            </section>
            <section className="result-section" aria-label="待验证假设">
              <div className="section-heading">
                <h2>
                  <CircleHelp size={18} /> 待验证假设
                </h2>
                <span className="count">{d.hypotheses.length}</span>
              </div>
              {d.hypotheses.length ? (
                <ul className="finding-list hypotheses">
                  {d.hypotheses.map((item, index) => (
                    <li key={index}>
                      <p>{item.statement}</p>
                      <small>
                        关联证据 {item.evidence_ids.join(" · ") || "无直接证据"}
                      </small>
                      <div className="subline">
                        验证：{item.verification_steps.join("；")}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <EmptyLine>当前没有提出待验证假设。</EmptyLine>
              )}
            </section>
          </div>
          <section className="result-section" aria-label="建议行动">
            <div className="section-heading">
              <h2>
                <ShieldAlert size={18} /> 建议行动
              </h2>
              <span className="count">{d.recommended_actions.length}</span>
            </div>
            {d.recommended_actions.length ? (
              <div className="action-list">
                {d.recommended_actions.map((item, index) => (
                  <div
                    className={`action-row ${item.requires_approval ? "action-approval" : ""}`}
                    key={index}
                  >
                    <span className="action-index">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                    <div className="action-main">
                      <strong>{item.action}</strong>
                      <p>{item.reason}</p>
                      {item.related_evidence_ids.length > 0 && (
                        <small>
                          证据 {item.related_evidence_ids.join(" · ")}
                        </small>
                      )}
                    </div>
                    <div className="action-flags">
                      <StatusBadge
                        status={
                          item.risk_level === "high"
                            ? "failed"
                            : item.risk_level === "medium"
                              ? "degraded"
                              : "ok"
                        }
                        text={`${item.risk_level.toUpperCase()} 风险`}
                      />
                      {item.requires_approval && (
                        <span className="approval-label">
                          <AlertTriangle size={14} /> 需审批
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyLine>暂无建议行动。</EmptyLine>
            )}
          </section>
          <section className="result-section" aria-label="证据缺口">
            <div className="section-heading">
              <h2>证据缺口</h2>
              <span className="count">{d.evidence_gaps.length}</span>
            </div>
            {d.evidence_gaps.length ? (
              <ul className="gap-list">
                {d.evidence_gaps.map((gap, index) => (
                  <li key={index}>
                    <strong>{gap.description}</strong>
                    <span>{gap.why_needed}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyLine>未列出额外证据缺口。</EmptyLine>
            )}
          </section>
        </>
      ) : (
        <section
          className="result-section structured-unavailable"
          aria-label="非结构化回复"
        >
          <FileText size={22} />
          <div>
            <h2>结构化诊断未生成</h2>
            <p>
              构建状态：{props.diagnosisStatus}。下面仍保留本次 Agent 回复。
            </p>
          </div>
        </section>
      )}

      {!clarification && (
        <div className="result-columns source-columns">
          <section className="result-section" aria-label="现场证据引用">
            <div className="section-heading">
              <h2>
                <Database size={18} /> 现场证据
              </h2>
              <span className="count">{props.evidenceRefs.length}</span>
            </div>
            {props.evidenceRefs.length || props.untypedEvidenceIds?.length ? (
              <ul className="reference-list">
                {props.evidenceRefs.map((ref) => (
                  <li key={ref.evidence_id}>
                    <code>{ref.evidence_id}</code>
                    <span>{ref.source_type}</span>
                  </li>
                ))}
                {!props.evidenceRefs.length &&
                  props.untypedEvidenceIds?.map((id) => (
                    <li key={id}>
                      <code>{id}</code>
                      <span>类型未返回</span>
                    </li>
                  ))}
              </ul>
            ) : (
              <EmptyLine>无现场证据引用。</EmptyLine>
            )}
          </section>
          <section className="result-section" aria-label="知识来源引用">
            <div className="section-heading">
              <h2>
                <BookOpen size={18} /> 知识来源
              </h2>
              <span className="count">{props.knowledgeRefs.length}</span>
            </div>
            {props.knowledgeRefs.length ? (
              <ul className="reference-list">
                {props.knowledgeRefs.map((ref) => (
                  <li key={ref.chunk_id}>
                    <code>
                      {ref.document_id} / {ref.chunk_id}
                    </code>
                    <span title={ref.source_ref}>{ref.source_ref}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyLine>无知识文档引用。</EmptyLine>
            )}
          </section>
        </div>
      )}
      {!clarification && Object.keys(props.toolStatus).length > 0 && (
        <section className="result-section" aria-label="工具状态">
          <div className="section-heading">
            <h2>工具状态</h2>
          </div>
          <div className="tool-status-list">
            {Object.entries(props.toolStatus).map(([name, status]) => (
              <div key={name}>
                <code>{name}</code>
                <StatusBadge status={status} />
              </div>
            ))}
          </div>
        </section>
      )}
      <details className="raw-response">
        <summary>原始 Markdown 回复</summary>
        <pre>{props.markdown}</pre>
      </details>
    </div>
  );
}
