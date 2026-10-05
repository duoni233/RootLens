import type {
  ChatRequest,
  ChatResponse,
  DiagnosisTrace,
  HistoryDetail,
  HistoryExplanation,
  HistoryFilters,
  HistoryPage,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function apiErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401)
      return "历史访问未获授权。请确认使用 ROOTLENS_HISTORY_API_TOKEN；若令牌正确，请刷新页面重试。";
    if (error.status === 404) return "记录不存在，或历史接口尚未启用。";
    if (error.status === 409) return "该记录使用了当前界面不支持的数据版本。";
    if (error.status === 503) return "后端服务或历史存储暂不可用。";
    if (error.status === 422) return "输入或筛选条件无效。";
    return `请求失败（HTTP ${error.status}）。`;
  }
  return "网络连接失败，请检查 RootLens 服务。";
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  historyToken?: string,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set("Content-Type", "application/json");
  if (historyToken !== undefined)
    headers.set("X-RootLens-History-Token", historyToken);
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { ...options, headers });
  } catch {
    throw new ApiError(0, "network");
  }
  if (!response.ok) throw new ApiError(response.status, "request failed");
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string }>("/health"),
  chat: (body: ChatRequest) =>
    request<ChatResponse>("/chat", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  history: (filters: HistoryFilters, token: string) => {
    const params = new URLSearchParams({
      limit: String(filters.limit),
      offset: String(filters.offset),
    });
    if (filters.service_name) params.set("service_name", filters.service_name);
    if (filters.diagnosis_status)
      params.set("diagnosis_status", filters.diagnosis_status);
    if (filters.degraded) params.set("degraded", filters.degraded);
    if (filters.service_missing)
      params.set("service_missing", filters.service_missing);
    if (filters.clarification_required)
      params.set("clarification_required", filters.clarification_required);
    return request<HistoryPage>(`/diagnoses?${params}`, {}, token);
  },
  detail: (runId: string, token: string) =>
    request<HistoryDetail>(
      `/diagnoses/${encodeURIComponent(runId)}`,
      {},
      token,
    ),
  explain: (runId: string, question: string, token: string) =>
    request<HistoryExplanation>(
      `/diagnoses/${encodeURIComponent(runId)}/explain`,
      { method: "POST", body: JSON.stringify({ question }) },
      token,
    ),
  trace: (runId: string, token: string) =>
    request<DiagnosisTrace>(
      `/diagnoses/${encodeURIComponent(runId)}/trace`,
      {},
      token,
    ),
};
