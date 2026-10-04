import {
  ArrowLeft,
  ArrowRight,
  Filter,
  LockKeyhole,
  RotateCcw,
  Search,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { HistoryAccess } from "../components/HistoryAccess";
import { StatusBadge } from "../components/StatusBadge";
import { useHistoryAccess } from "../historyAccess";
import { api, apiErrorMessage, ApiError } from "../lib/api";
import {
  buildStatuses,
  displayStatus,
  formatDate,
  runStatus,
} from "../lib/format";
import type {
  DiagnosisBuildStatus,
  HistoryPage as HistoryPageResult,
} from "../lib/types";

const LIMIT = 15;
type StatusFilter = DiagnosisBuildStatus | "clarification" | "";

export function HistoryPage() {
  const { token, lock } = useHistoryAccess();
  const [serviceInput, setServiceInput] = useState("");
  const [service, setService] = useState("");
  const [status, setStatus] = useState<StatusFilter>("");
  const [degraded, setDegraded] = useState<"" | "true" | "false">("");
  const [serviceMissing, setServiceMissing] = useState<"" | "true" | "false">(
    "",
  );
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<HistoryPageResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) {
      setPage(null);
      return;
    }
    let active = true;
    setLoading(true);
    setError("");
    api
      .history(
        {
          limit: LIMIT,
          offset,
          service_name: serviceMissing === "true" ? "" : service,
          service_missing: serviceMissing,
          diagnosis_status: status === "clarification" ? "" : status,
          clarification_required: status === "clarification" ? "true" : "",
          degraded,
        },
        token,
      )
      .then((value) => {
        if (active) setPage(value);
      })
      .catch((cause: unknown) => {
        if (active) {
          setPage(null);
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
  }, [token, offset, service, serviceMissing, status, degraded, lock]);

  function clearFilters() {
    setServiceInput("");
    setService("");
    setServiceMissing("");
    setStatus("");
    setDegraded("");
    setOffset(0);
  }

  return (
    <div className="page history-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">ARCHIVE / DIAGNOSES</span>
          <h1>诊断历史</h1>
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
          <form
            className="filter-bar"
            onSubmit={(event) => {
              event.preventDefault();
              setOffset(0);
              setService(serviceInput.trim());
            }}
          >
            <div className="filter-search">
              <Search size={16} />
              <input
                aria-label="按服务筛选"
                placeholder="服务名包含，例如 pay"
                value={serviceInput}
                onChange={(event) => setServiceInput(event.target.value)}
                disabled={serviceMissing === "true"}
              />
            </div>
            <label>
              <span>服务识别</span>
              <select
                value={serviceMissing}
                onChange={(event) => {
                  const next = event.target.value as typeof serviceMissing;
                  setServiceMissing(next);
                  if (next === "true") {
                    setServiceInput("");
                    setService("");
                  }
                  setOffset(0);
                }}
              >
                <option value="">全部</option>
                <option value="false">已识别服务</option>
                <option value="true">服务待确认</option>
              </select>
            </label>
            <label>
              <span>诊断状态</span>
              <select
                value={status}
                onChange={(event) => {
                  setStatus(event.target.value as StatusFilter);
                  setOffset(0);
                }}
              >
                <option value="">全部</option>
                <option value="clarification">待补充信息</option>
                {buildStatuses.map((value) => (
                  <option key={value} value={value}>
                    {displayStatus(value)}
                  </option>
                ))}
              </select>
            </label>
            <label title="部分工具、Agent 或结构化诊断失败，但系统仍可能返回了结果；不等于待补充信息。">
              <span>降级</span>
              <select
                value={degraded}
                onChange={(event) => {
                  setDegraded(event.target.value as typeof degraded);
                  setOffset(0);
                }}
              >
                <option value="">全部</option>
                <option value="true">是</option>
                <option value="false">否</option>
              </select>
            </label>
            <button className="button-secondary" type="submit">
              <Filter size={16} /> 筛选
            </button>
            <button
              className="button-quiet"
              type="button"
              onClick={clearFilters}
            >
              <RotateCcw size={15} /> 清空筛选
            </button>
          </form>
          {error && (
            <div className="notice-error" role="alert">
              {error}
              <button type="button" className="button-quiet" onClick={lock}>
                更换令牌
              </button>
            </div>
          )}
          <div className="history-toolbar">
            <span>
              {loading ? "加载中…" : `本页 ${page?.items.length ?? 0} 条`}
            </span>
            <span>按创建时间倒序</span>
          </div>
          <div className="history-table-wrap">
            <table className="history-table">
              <thead>
                <tr>
                  <th>创建时间</th>
                  <th>服务</th>
                  <th>意图</th>
                  <th>主 Agent</th>
                  <th>状态</th>
                  <th>详情</th>
                </tr>
              </thead>
              <tbody>
                {page?.items.map((run) => (
                  <tr key={run.run_id}>
                    <td>{formatDate(run.created_at)}</td>
                    <td className="strong-cell">
                      {run.service_name || "服务待确认"}
                    </td>
                    <td>
                      <code>{run.intent}</code>
                    </td>
                    <td>{run.primary_agent || "未执行"}</td>
                    <td>
                      <StatusBadge status={runStatus(run)} />
                    </td>
                    <td>
                      <Link
                        to={`/history/${run.run_id}`}
                        className="icon-link"
                        aria-label={`查看 ${run.run_id}`}
                        title="查看详情"
                      >
                        <ArrowRight size={17} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!loading && !error && page?.items.length === 0 && (
              <div className="table-empty">没有符合条件的历史记录。</div>
            )}
          </div>
          <div className="pagination">
            <button
              className="button-quiet"
              type="button"
              disabled={offset === 0 || loading}
              onClick={() => setOffset(Math.max(0, offset - LIMIT))}
            >
              <ArrowLeft size={16} /> 上一页
            </button>
            <span>第 {Math.floor(offset / LIMIT) + 1} 页</span>
            <button
              className="button-quiet"
              type="button"
              disabled={loading || (page?.items.length ?? 0) < LIMIT}
              onClick={() => setOffset(offset + LIMIT)}
            >
              下一页 <ArrowRight size={16} />
            </button>
          </div>
        </>
      )}
    </div>
  );
}
