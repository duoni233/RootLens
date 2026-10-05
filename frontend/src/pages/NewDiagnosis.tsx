import { ArrowRight, RotateCcw, SearchCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { HistoryAccess } from "../components/HistoryAccess";
import { useHistoryAccess } from "../historyAccess";
import { api, apiErrorMessage, ApiError } from "../lib/api";
import type { ChatResponse, EvidenceRef, HistoryDetail } from "../lib/types";
import { DiagnosisView } from "../components/DiagnosisView";
import { suggestDemoEventTime } from "../lib/eventTime";

function composeClarification(parts: string[], reply: string): string {
  if (parts.length === 0) return reply;
  return [
    parts[0],
    ...parts.slice(1).map((part) => `补充信息：${part}`),
    `补充信息：${reply}`,
  ].join("\n");
}

export function NewDiagnosis() {
  const [searchParams, setSearchParams] = useSearchParams();
  const sourceRunId = searchParams.get("from");
  const { token, lock } = useHistoryAccess();
  const [source, setSource] = useState<HistoryDetail | null>(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourceError, setSourceError] = useState("");
  const [historyMode, setHistoryMode] = useState<"explain" | "rediagnose">(
    "explain",
  );
  const [explanation, setExplanation] = useState("");
  const [message, setMessage] = useState("");
  const [anchorTime, setAnchorTime] = useState("");
  const [anchorTouched, setAnchorTouched] = useState(false);
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
    setHistoryMode("explain");
    setExplanation("");
    setResult(null);
    setConvId(null);
    setPendingParts([]);
    setSourceLoading(true);
    setSourceError("");
    api
      .detail(sourceRunId, token)
      .then((value) => {
        if (active) {
          setSource(value);
          setAnchorTime(suggestDemoEventTime(value.original_message));
          setAnchorTouched(false);
        }
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
    if (source && historyMode === "explain") {
      setBusy(true);
      setError("");
      try {
        const response = await api.explain(source.run_id, reply, token);
        setExplanation(response.answer);
        setMessage("");
      } catch (cause) {
        setError(apiErrorMessage(cause));
      } finally {
        setBusy(false);
      }
      return;
    }
    const requestMessage = clarification
      ? composeClarification(pendingParts, reply)
      : source?.service_name && !reply.includes(source.service_name)
        ? `${source.service_name}：${reply}`
        : reply;
    setBusy(true);
    setError("");
    try {
      const response = await api.chat({
        message: requestMessage,
        environment: "demo",
        ...(anchorTime ? { anchor_time: `${anchorTime}:00+08:00` } : {}),
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
    setAnchorTouched(false);
    setExplanation("");
    setHistoryMode("explain");
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
          <h1>{sourceRunId ? "历史记录追问" : "新建诊断"}</h1>
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
            {source.original_message.length > 400 ? (
              <details className="history-long-input">
                <summary>查看历史输入</summary>
                <p>{source.original_message}</p>
              </details>
            ) : (
              <p>
                <strong>原始问题：</strong>
                {source.original_message}
              </p>
            )}
            {source.diagnosis?.summary && (
              <p>
                <strong>上次诊断摘要：</strong>
                {source.diagnosis.summary}
              </p>
            )}
            <small>
              解读只使用这条已保存记录；重新诊断才会查询 demo 现场数据。
            </small>
          </section>
        )}
      {source && (!source.environment || source.environment === "demo") && (
        <div className="history-mode" role="group" aria-label="追问方式">
          <button
            type="button"
            className={historyMode === "explain" ? "active" : ""}
            aria-pressed={historyMode === "explain"}
            onClick={() => {
              setHistoryMode("explain");
              setMessage("");
              setError("");
            }}
          >
            解读已有记录
          </button>
          <button
            type="button"
            className={historyMode === "rediagnose" ? "active" : ""}
            aria-pressed={historyMode === "rediagnose"}
            onClick={() => {
              setHistoryMode("rediagnose");
              setMessage("");
              setError("");
            }}
          >
            重新诊断
          </button>
        </div>
      )}
      {sourceRunId && historyMode === "explain" && explanation && (
        <section className="history-answer" aria-label="历史解读">
          <h2>历史解读</h2>
          <p>{explanation}</p>
          <small>依据已归档内容回答；没有重新查询现场证据。</small>
        </section>
      )}
      {result && (!sourceRunId || historyMode === "rediagnose") && (
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
          {historyMode === "rediagnose" && source && (
            <p className="form-intro">
              请描述要重新调查的故障。来源服务会自动带入，但旧结论不会当作新证据。
            </p>
          )}
          {(!source || historyMode === "rediagnose") && result && (
            <h2>{clarification ? "补充诊断信息" : "继续提问"}</h2>
          )}
          {(!source || historyMode === "rediagnose") &&
            clarification &&
            pendingParts.length > 0 && (
              <div className="pending-context">
                <strong>已提供的信息</strong>
                {pendingParts.map((part, index) => (
                  <p key={index}>{part}</p>
                ))}
              </div>
            )}
          <label htmlFor="incident-message">
            {source && historyMode === "explain"
              ? "关于这条记录的问题"
              : clarification
                ? "补充信息"
                : "故障描述"}
          </label>
          <textarea
            id="incident-message"
            rows={clarification ? 3 : 5}
            maxLength={source && historyMode === "explain" ? 1000 : 4000}
            placeholder={
              source && historyMode === "explain"
                ? "例如：哪些是已确认事实，哪些还只是待验证假设？"
                : clarification
                  ? "补充受影响的服务、发生时间或错误信息…"
                  : "例如：payment-service 从 10:05 开始出现 5xx 激增，刚发布 v2.3.7…"
            }
            value={message}
            onChange={(event) => {
              const next = event.target.value;
              setMessage(next);
              if (!anchorTouched && (!source || historyMode === "rediagnose"))
                setAnchorTime(
                  suggestDemoEventTime(next) ||
                    (source
                      ? suggestDemoEventTime(source.original_message)
                      : ""),
                );
            }}
            required
          />
          {source && historyMode === "explain" && (
            <small className="history-model-notice">
              {source.clarification_required || !source.diagnosis
                ? "这条记录没有完整诊断；系统只会说明档案的缺口，不调用模型。"
                : "提交后会把这条记录的结构化诊断和你的问题发送给当前配置的模型。"}
              不发送完整日志，也不会把补充内容写入知识库。
            </small>
          )}
          <div className="form-bottom">
            {(!source || historyMode === "rediagnose") && (
              <div className="form-fields">
                <div className="demo-environment">
                  <span className="field-label">数据环境</span>
                  <strong>demo · 模拟数据</strong>
                  <small>未连接 staging 或 prod</small>
                </div>
                <div>
                  <label htmlFor="anchor-time">事件时间（北京时间）</label>
                  <input
                    id="anchor-time"
                    type="datetime-local"
                    value={anchorTime}
                    onChange={(event) => {
                      setAnchorTime(event.target.value);
                      setAnchorTouched(true);
                    }}
                  />
                  <small>
                    {anchorTime && !anchorTouched
                      ? "根据描述推定时间；未写日期时采用 demo 样本日期，可修改。"
                      : "demo 仅有已登记的模拟故障；请填故障发生时间。"}
                  </small>
                </div>
              </div>
            )}
            <button
              className="button-primary submit-button"
              type="submit"
              disabled={busy || !message.trim()}
            >
              {busy
                ? source && historyMode === "explain"
                  ? "解读中…"
                  : "诊断中…"
                : source && historyMode === "explain"
                  ? "解读记录"
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
          {(!source || historyMode === "rediagnose") && convId && (
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
