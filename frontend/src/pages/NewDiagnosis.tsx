import { ArrowRight, RotateCcw, SearchCheck } from "lucide-react";
import { useState } from "react";
import { api, apiErrorMessage } from "../lib/api";
import type { ChatResponse, EvidenceRef } from "../lib/types";
import { DiagnosisView } from "../components/DiagnosisView";

export function NewDiagnosis() {
  const [message, setMessage] = useState("");
  const [environment, setEnvironment] = useState<"demo" | "staging" | "prod">(
    "demo",
  );
  const [anchorTime, setAnchorTime] = useState("");
  const [convId, setConvId] = useState<string | null>(null);
  const [result, setResult] = useState<ChatResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!message.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const response = await api.chat({
        message: message.trim(),
        environment,
        ...(anchorTime
          ? { anchor_time: new Date(anchorTime).toISOString() }
          : {}),
        ...(convId ? { conv_id: convId } : {}),
      });
      setResult(response);
      setConvId(response.conv_id);
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
    setMessage("");
    setAnchorTime("");
    setError("");
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
          <h1>新建诊断</h1>
        </div>
        {convId && (
          <button
            type="button"
            className="button-quiet"
            onClick={reset}
            title="新建会话"
          >
            <RotateCcw size={16} /> 新会话
          </button>
        )}
      </header>
      <form className="diagnosis-form" onSubmit={submit}>
        <label htmlFor="incident-message">故障描述</label>
        <textarea
          id="incident-message"
          rows={5}
          maxLength={4000}
          placeholder="例如：payment-service 从 10:05 开始出现 5xx 激增，刚发布 v2.3.7…"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          required
        />
        <div className="form-bottom">
          <div className="form-fields">
            <div>
              <label htmlFor="environment">环境</label>
              <select
                id="environment"
                value={environment}
                onChange={(event) =>
                  setEnvironment(event.target.value as typeof environment)
                }
              >
                <option value="demo">demo</option>
                <option value="staging">staging</option>
                <option value="prod">prod</option>
              </select>
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
            {busy ? "诊断中…" : "开始诊断"}{" "}
            {busy ? (
              <SearchCheck size={17} className="pulse-icon" />
            ) : (
              <ArrowRight size={17} />
            )}
          </button>
        </div>
        {convId && (
          <small className="session-label">
            会话 {convId.slice(0, 8)} · 下一次提交继续使用当前会话
          </small>
        )}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </form>
      {result && (
        <div className="result-wrap">
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
            environment={result.diagnosis?.environment ?? environment}
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
    </div>
  );
}
