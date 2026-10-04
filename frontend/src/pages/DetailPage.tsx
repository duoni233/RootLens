import { ArrowLeft, ArrowRight, LockKeyhole } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { DiagnosisView } from "../components/DiagnosisView";
import { HistoryAccess } from "../components/HistoryAccess";
import { TraceTimeline } from "../components/TraceTimeline";
import { useHistoryAccess } from "../historyAccess";
import { api, apiErrorMessage, ApiError } from "../lib/api";
import { formatDate } from "../lib/format";
import type { DiagnosisTrace, HistoryDetail } from "../lib/types";

export function DetailPage() {
  const { runId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const { token, lock } = useHistoryAccess();
  const [detail, setDetail] = useState<HistoryDetail | null>(null);
  const [trace, setTrace] = useState<DiagnosisTrace | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const view = params.get("view") === "trace" ? "trace" : "diagnosis";

  useEffect(() => {
    setTrace(null);
  }, [runId]);

  useEffect(() => {
    if (!token || !runId) {
      setDetail(null);
      return;
    }
    let active = true;
    setLoading(true);
    setError("");
    api
      .detail(runId, token)
      .then((value) => {
        if (active) setDetail(value);
      })
      .catch((cause: unknown) => {
        if (active) {
          setDetail(null);
          setError(apiErrorMessage(cause));
          if (cause instanceof ApiError && cause.status === 401) lock();
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [runId, token, lock]);

  useEffect(() => {
    if (view !== "trace" || !token || !runId || trace) return;
    let active = true;
    api
      .trace(runId, token)
      .then((value) => {
        if (active) setTrace(value);
      })
      .catch((cause: unknown) => {
        if (active) {
          setError(apiErrorMessage(cause));
          if (cause instanceof ApiError && cause.status === 401) lock();
        }
      });
    return () => {
      active = false;
    };
  }, [view, token, runId, trace, lock]);

  return (
    <div className="page detail-page">
      <header className="page-header">
        <div>
          <Link className="back-link" to="/history">
            <ArrowLeft size={15} /> 返回历史
          </Link>
          <span className="eyebrow">ARCHIVE / RUN {runId.slice(0, 8)}</span>
          <h1>{detail?.service_name || "诊断详情"}</h1>
          <p>{detail ? formatDate(detail.created_at) : "加载历史记录"}</p>
        </div>
        {token && (
          <button className="button-quiet" type="button" onClick={lock}>
            <LockKeyhole size={16} /> 锁定历史
          </button>
        )}
      </header>
      {!token ? (
        <HistoryAccess error={error} />
      ) : (
        <>
          <div className="view-tabs" role="tablist" aria-label="诊断详情视图">
            <button
              role="tab"
              aria-selected={view === "diagnosis"}
              className={view === "diagnosis" ? "active" : ""}
              onClick={() => setParams({})}
            >
              诊断结果
            </button>
            <button
              role="tab"
              aria-selected={view === "trace"}
              className={view === "trace" ? "active" : ""}
              onClick={() => setParams({ view: "trace" })}
            >
              执行轨迹
            </button>
          </div>
          {error && (
            <div className="notice-error" role="alert">
              {error}
            </div>
          )}
          {loading && <p className="loading-line">加载中…</p>}
          {!loading && detail && view === "diagnosis" && (
            <section className="history-original" aria-label="原始问题">
              <div className="history-original-heading">
                <h2>原始问题</h2>
                {(detail.environment === "demo" || !detail.environment) && (
                  <Link
                    className="inline-link"
                    to={`/?from=${encodeURIComponent(detail.run_id)}`}
                  >
                    基于此记录追问 <ArrowRight size={15} />
                  </Link>
                )}
              </div>
              <p>{detail.original_message}</p>
              {detail.environment && detail.environment !== "demo" && (
                <small>
                  此记录不属于 demo 数据环境，当前控制台不能基于它发起追问。
                </small>
              )}
            </section>
          )}
          {!loading && detail && view === "diagnosis" && (
            <DiagnosisView
              diagnosis={detail.diagnosis}
              markdown={detail.response_markdown}
              diagnosisStatus={detail.diagnosis_status}
              intent={detail.intent}
              primaryAgent={detail.primary_agent}
              supportingAgents={detail.supporting_agents}
              serviceName={detail.service_name}
              environment={detail.environment}
              runId={detail.run_id}
              degraded={detail.degraded}
              clarificationRequired={detail.clarification_required}
              evidenceRefs={detail.evidence_refs}
              knowledgeRefs={detail.knowledge_refs}
              toolStatus={detail.diagnosis?.tool_status ?? {}}
            />
          )}
          {!loading &&
            detail &&
            view === "trace" &&
            (trace ? (
              <TraceTimeline trace={trace} />
            ) : (
              !error && <p className="loading-line">加载执行轨迹…</p>
            ))}
          {detail && (
            <p className="history-boundary">
              历史记录仅保存来源引用，未归档完整日志、指标载荷或 Runbook 正文。
            </p>
          )}
        </>
      )}
    </div>
  );
}
