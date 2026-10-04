import { ArrowRight, RotateCcw, SearchCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { HistoryAccess } from "../components/HistoryAccess";
import { useHistoryAccess } from "../historyAccess";
import { api, apiErrorMessage, ApiError } from "../lib/api";
import type { ChatResponse, EvidenceRef, HistoryDetail } from "../lib/types";
import { DiagnosisView } from "../components/DiagnosisView";

function composeClarification(parts: string[], reply: string): string {
  if (parts.length === 0) return reply;
  return [
    parts[0],
    ...parts.slice(1).map((part) => `补充信息：${part}`),
    `补充信息：${reply}`,
  ].join("\n");
}

function composeHistoryQuestion(source: HistoryDetail, reply: string): string {
  return [
    `原始问题：${source.original_message}`,
    ...(source.diagnosis?.summary
      ? [
          `上次诊断摘要（历史结论，不作为当前现场证据）：${source.diagnosis.summary}`,
        ]
      : []),
    `新的追问：${reply}`,
  ].join("\n\n");
}

export function NewDiagnosis() {
  const [searchParams, setSearchParams] = useSearchParams();
  const sourceRunId = searchParams.get("from");
  const { token, lock } = useHistoryAccess();
  const [source, setSource] = useState<HistoryDetail | null>(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourceError, setSourceError] = useState("");
  const [message, setMessage] = useState("");
  const [anchorTime, setAnchorTime] = useState("");
  const [convId, setConvId] = useState<string | null>(null);
  const [result, setResult] = useState<ChatResponse | null>(null);
  const [pendingParts, setPendingParts] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const resultRef = useRef<HTMLDivElement>(null);
  const clarification = result?.clarification_required ?? false;

  useEffect(() => {
    if (!sourceRunId || !token) {
      setSource(null);
      setSourceLoading(false);
      return;
    }
    let active = true;
    setSource(null);
    setSourceLoading(true);
    setSourceError("");
    api
      .detail(sourceRunId, token)
      .then((value) => {
        if (active) setSource(value);
      })
      .catch((cause: unknown) => {
        if (active) {
          setSourceError(apiErrorMessage(cause));
          if (cause instanceof ApiError && cause.status === 401) lock();
        }
      })
      .finally(() => {
        if (active) setSourceLoading(false);
      });
    return () => {
      active = false;
    };
  }, [sourceRunId, token, lock]);

  useEffect(() => {
    if (result)
      resultRef.current?.scrollIntoView?.({
        block: "start",
        behavior: "smooth",
      });
  }, [result]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const reply = message.trim();
    if (!reply || busy || (sourceRunId && !source)) return;
    const requestMessage = clarification
      ? composeClarification(pendingParts, reply)
      : source && !convId
        ? composeHistoryQuestion(source, reply)
        : reply;
    setBusy(true);
    setError("");
    try {
      const response = await api.chat({
        message: requestMessage,
        environment: "demo",
        ...(anchorTime
          ? { anchor_time: new Date(anchorTime).toISOString() }
          : {}),
        ...(convId ? { conv_id: convId } : {}),
      });
      setResult(response);
      setConvId(response.conv_id);
      setPendingParts(
        response.clarification_required
          ? clarification
            ? [...pendingParts, reply]
            : [requestMessage]
          : [],
      );
      setMessage("");
    } catch (cause) {
      setError(apiErrorMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setConvId(null);
    setResult(null);
    setPendingParts([]);
    setMessage("");
    setAnchorTime("");
    setError("");
    setSource(null);
    setSourceError("");
    if (sourceRunId) setSearchParams({});
  }

  const evidenceRefs: EvidenceRef[] = result?.diagnosis?.evidence_refs ?? [];
  const serviceName =
    result?.diagnosis?.affected_services[0] ??
    result?.entities.service_name?.[0] ??
    null;
  return (
    <div className="page new-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">WORKSPACE / DIAGNOSIS</span>
          <h1>{sourceRunId ? "基于历史追问" : "新建诊断"}</h1>
        </div>
        {(convId || sourceRunId) && (
          <button
            type="button"
            className="button-quiet"
            onClick={reset}
            title="开始另一条诊断"
          >
            <RotateCcw size={16} /> 新诊断
          </button>
        )}
      </header>
      {sourceRunId && !token && <HistoryAccess error={sourceError} />}
      {sourceRunId && token && sourceLoading && (
        <p className="loading-line">加载历史上下文…</p>
      )}
      {sourceRunId && token && sourceError && (
        <p className="notice-error" role="alert">
          {sourceError}
        </p>
      )}
      {sourceRunId &&
        source &&
        source.environment &&
        source.environment !== "demo" && (
          <p className="notice-error" role="alert">
            这条记录不属于 demo 数据环境，当前控制台不能基于它重新诊断。
          </p>
        )}
      {sourceRunId &&
        source &&
        (!source.environment || source.environment === "demo") && (
          <section className="history-source" aria-label="历史上下文">
            <div className="history-original-heading">
              <h2>来源记录</h2>
              <Link className="inline-link" to={`/history/${source.run_id}`}>
                查看原记录 <ArrowRight size={15} />
              </Link>
            </div>
            <p>
              <strong>原始问题：</strong>
              {source.original_message}
            </p>
            {source.diagnosis?.summary && (
              <p>
                <strong>上次诊断摘要：</strong>
                {source.diagnosis.summary}
              </p>
            )}
            <small>
              本次将创建新诊断并重新取证；旧结论只作背景参考，不会恢复旧会话。
            </small>
          </section>
        )}
      {result && (
        <div className="result-wrap" ref={resultRef}>
          <div className="result-heading">
            <span className="eyebrow">LATEST RUN</span>
            <span>{result.latency_ms.toFixed(0)} ms</span>
          </div>
          <DiagnosisView
            diagnosis={result.diagnosis}
            markdown={result.response}
            diagnosisStatus={result.diagnosis_status}
            intent={result.intent}
            primaryAgent={result.primary_agent || null}
            supportingAgents={result.supporting_agents}
            serviceName={serviceName}
            environment={result.diagnosis?.environment ?? "demo"}
            runId={result.run_id}
            persistenceStatus={result.persistence_status}
            degraded={
              result.diagnosis?.degraded ??
              Object.values(result.tool_status).some(
                (status) => status === "failed" || status === "degraded",
              )
            }
            clarificationRequired={result.clarification_required}
            evidenceRefs={evidenceRefs}
            untypedEvidenceIds={result.evidence_ids}
            knowledgeRefs={result.diagnosis?.knowledge_refs ?? []}
            toolStatus={result.tool_status}
          />
        </div>
      )}
      {(!sourceRunId ||
        (source && (!source.environment || source.environment === "demo"))) && (
        <form className="diagnosis-form" onSubmit={submit}>
          {result && <h2>{clarification ? "补充诊断信息" : "继续提问"}</h2>}
          {clarification && pendingParts.length > 0 && (
            <div className="pending-context">
              <strong>已提供的信息</strong>
              {pendingParts.map((part, index) => (
                <p key={index}>{part}</p>
              ))}
            </div>
          )}
          <label htmlFor="incident-message">
            {clarification
              ? "补充信息"
              : source && !convId
                ? "新的追问"
                : "故障描述"}
          </label>
          <textarea
            id="incident-message"
            rows={clarification ? 3 : 5}
            maxLength={4000}
            placeholder={
              clarification
                ? "补充受影响的服务、发生时间或错误信息…"
                : source && !convId
                  ? "围绕这条历史诊断继续提问，或补充新的故障线索…"
                  : "例如：payment-service 从 10:05 开始出现 5xx 激增，刚发布 v2.3.7…"
            }
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            required
          />
          <div className="form-bottom">
            <div className="form-fields">
              <div className="demo-environment">
                <span className="field-label">数据环境</span>
                <strong>demo · 模拟数据</strong>
                <small>未连接 staging 或 prod</small>
              </div>
              <div>
                <label htmlFor="anchor-time">事件时间</label>
                <input
                  id="anchor-time"
                  type="datetime-local"
                  value={anchorTime}
                  onChange={(event) => setAnchorTime(event.target.value)}
                />
              </div>
            </div>
            <button
              className="button-primary submit-button"
              type="submit"
              disabled={busy || !message.trim()}
            >
              {busy
                ? "诊断中…"
                : clarification
                  ? "提交补充"
                  : result
                    ? "继续诊断"
                    : "开始诊断"}{" "}
              {busy ? (
                <SearchCheck size={17} className="pulse-icon" />
              ) : (
                <ArrowRight size={17} />
              )}
            </button>
          </div>
          {convId && (
            <small className="session-label">
              会话 {convId.slice(0, 8)} · 本次提交沿用当前会话
            </small>
          )}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </form>
      )}
    </div>
  );
}
