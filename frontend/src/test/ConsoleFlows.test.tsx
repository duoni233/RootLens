import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HistoryAccessProvider } from "../historyAccess";
import { NewDiagnosis } from "../pages/NewDiagnosis";
import { HistoryPage } from "../pages/HistoryPage";
import { DetailPage } from "../pages/DetailPage";
import { api } from "../lib/api";
import { chatResponse, detail, trace } from "./fixtures";

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function show(node: React.ReactNode, path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <HistoryAccessProvider>{node}</HistoryAccessProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  sessionStorage.clear();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("console flows", () => {
  it("submits /chat and displays the structured result and saved run", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(chatResponse));
    vi.stubGlobal("fetch", fetchMock);
    show(<NewDiagnosis />);
    fireEvent.change(screen.getByLabelText("故障描述"), {
      target: { value: "payment-service 出现 5xx" },
    });
    fireEvent.click(screen.getByRole("button", { name: /开始诊断/ }));
    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: "已确认事实" }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: /查看记录/ })).toHaveAttribute(
      "href",
      "/history/run-1",
    );
    const options = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(options.body)).environment).toBe("demo");
    expect(new Headers(options.headers).has("X-RootLens-History-Token")).toBe(
      false,
    );
    expect(screen.getByText("demo · 模拟数据")).toBeVisible();
    expect(
      screen.queryByRole("option", { name: "prod" }),
    ).not.toBeInTheDocument();
  });

  it("continues a clarification with original details and the same conversation", async () => {
    const clarification = {
      ...chatResponse,
      response: "请提供受影响的服务名和故障发生时间。",
      clarification_required: true,
      diagnosis: null,
      diagnosis_status: "not_run",
      run_id: "clarification-run",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(clarification))
      .mockResolvedValueOnce(json(chatResponse));
    vi.stubGlobal("fetch", fetchMock);
    show(<NewDiagnosis />);
    fireEvent.change(screen.getByLabelText("故障描述"), {
      target: { value: "后台界面打不开" },
    });
    fireEvent.click(screen.getByRole("button", { name: /开始诊断/ }));
    await waitFor(() =>
      expect(screen.getByLabelText("补充信息")).toBeVisible(),
    );
    expect(screen.getByText("后台界面打不开")).toBeVisible();
    fireEvent.change(screen.getByLabelText("补充信息"), {
      target: { value: "payment-service 从 10:05 开始报 500" },
    });
    fireEvent.click(screen.getByRole("button", { name: /提交补充/ }));
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "已确认事实" })).toBeVisible(),
    );
    const second = JSON.parse(
      String((fetchMock.mock.calls[1][1] as RequestInit).body),
    );
    expect(second.message).toContain("后台界面打不开");
    expect(second.message).toContain("payment-service 从 10:05 开始报 500");
    expect(second.conv_id).toBe("conv-1");
    expect(second.environment).toBe("demo");
  });

  it("allows a second question without merging it and resets for a new diagnosis", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json(chatResponse));
    vi.stubGlobal("fetch", fetchMock);
    show(<NewDiagnosis />);
    fireEvent.change(screen.getByLabelText("故障描述"), {
      target: { value: "payment-service 10:05 出现 5xx" },
    });
    fireEvent.click(screen.getByRole("button", { name: /开始诊断/ }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /继续诊断/ })).toBeVisible(),
    );
    fireEvent.change(screen.getByLabelText("故障描述"), {
      target: { value: "另一个故障" },
    });
    fireEvent.click(screen.getByRole("button", { name: /继续诊断/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const second = JSON.parse(
      String((fetchMock.mock.calls[1][1] as RequestInit).body),
    );
    expect(second.message).toBe("另一个故障");
    expect(second.conv_id).toBe("conv-1");
    fireEvent.click(screen.getByRole("button", { name: "新诊断" }));
    fireEvent.change(screen.getByLabelText("故障描述"), {
      target: { value: "独立事件" },
    });
    fireEvent.click(screen.getByRole("button", { name: /开始诊断/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const third = JSON.parse(
      String((fetchMock.mock.calls[2][1] as RequestInit).body),
    );
    expect(third.conv_id).toBeUndefined();
  });

  it("requires an entered token, sends it only with history and can lock again", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        json({
          items: [
            {
              run_id: "run-1",
              created_at: detail.created_at,
              service_name: detail.service_name,
              intent: detail.intent,
              primary_agent: detail.primary_agent,
              diagnosis_status: "success",
              degraded: false,
              clarification_required: false,
            },
          ],
          limit: 15,
          offset: 0,
        }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    show(<HistoryPage />, "/history");
    expect(screen.getByRole("region", { name: "解锁诊断历史" })).toBeVisible();
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("访问令牌"), {
      target: { value: "private-test-token" },
    });
    fireEvent.click(screen.getByRole("button", { name: /解锁/ }));
    await waitFor(() =>
      expect(screen.getByText("payment-service")).toBeInTheDocument(),
    );
    const options = fetchMock.mock.calls[0][1] as RequestInit;
    expect(new Headers(options.headers).get("X-RootLens-History-Token")).toBe(
      "private-test-token",
    );
    expect(sessionStorage.getItem("rootlens-history-token")).toBe(
      "private-test-token",
    );
    fireEvent.click(screen.getByRole("button", { name: "锁定历史" }));
    expect(sessionStorage.getItem("rootlens-history-token")).toBeNull();
  });

  it("handles unauthorized token without showing records", async () => {
    sessionStorage.setItem("rootlens-history-token", "wrong");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({}, 401)));
    show(<HistoryPage />, "/history");
    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: "解锁诊断历史" }),
      ).toBeInTheDocument(),
    );
    expect(sessionStorage.getItem("rootlens-history-token")).toBeNull();
    expect(screen.queryByText("payment-service")).not.toBeInTheDocument();
  });

  it("rejects an entered invalid token before unlocking and explains why", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({}, 401));
    vi.stubGlobal("fetch", fetchMock);
    show(<HistoryPage />, "/history");
    fireEvent.change(screen.getByLabelText("访问令牌"), {
      target: { value: "wrong-token" },
    });
    fireEvent.click(screen.getByRole("button", { name: /解锁/ }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "ROOTLENS_HISTORY_API_TOKEN",
      ),
    );
    expect(screen.getByRole("region", { name: "解锁诊断历史" })).toBeVisible();
    expect(sessionStorage.getItem("rootlens-history-token")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("applies service, status, and degraded filters to the history request", async () => {
    sessionStorage.setItem("rootlens-history-token", "token");
    const fetchMock = vi
      .fn()
      .mockResolvedValue(json({ items: [], limit: 15, offset: 0 }));
    vi.stubGlobal("fetch", fetchMock);
    show(<HistoryPage />, "/history");
    await waitFor(() =>
      expect(screen.getByText("没有符合条件的历史记录。")).toBeVisible(),
    );
    fireEvent.change(screen.getByLabelText("按服务筛选"), {
      target: { value: "order" },
    });
    fireEvent.change(screen.getByLabelText("诊断状态"), {
      target: { value: "parse_failed" },
    });
    fireEvent.change(screen.getByLabelText("降级"), {
      target: { value: "true" },
    });
    fireEvent.click(screen.getByRole("button", { name: "筛选" }));
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url]) =>
            String(url).includes("service_name=order") &&
            String(url).includes("diagnosis_status=parse_failed") &&
            String(url).includes("degraded=true"),
        ),
      ).toBe(true),
    );
  });

  it("filters unknown services and pending clarifications, then clears filters", async () => {
    sessionStorage.setItem("rootlens-history-token", "token");
    const fetchMock = vi
      .fn()
      .mockResolvedValue(json({ items: [], limit: 15, offset: 0 }));
    vi.stubGlobal("fetch", fetchMock);
    show(<HistoryPage />, "/history");
    fireEvent.change(screen.getByLabelText("服务识别"), {
      target: { value: "true" },
    });
    expect(screen.getByLabelText("按服务筛选")).toBeDisabled();
    fireEvent.change(screen.getByLabelText("诊断状态"), {
      target: { value: "clarification" },
    });
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([url]) =>
            String(url).includes("service_missing=true") &&
            String(url).includes("clarification_required=true") &&
            !String(url).includes("diagnosis_status="),
        ),
      ).toBe(true),
    );
    fireEvent.click(screen.getByRole("button", { name: "清空筛选" }));
    await waitFor(() => {
      const lastUrl = String(fetchMock.mock.calls.at(-1)?.[0]);
      expect(lastUrl).not.toContain("service_missing=");
      expect(lastUrl).not.toContain("clarification_required=");
    });
    expect(screen.getByLabelText("按服务筛选")).toBeEnabled();
  });

  it("loads detail and trace separately, showing only persisted references", async () => {
    sessionStorage.setItem("rootlens-history-token", "token");
    const fetchMock = vi
      .fn()
      .mockImplementation((url: string) =>
        Promise.resolve(json(url.endsWith("/trace") ? trace : detail)),
      );
    vi.stubGlobal("fetch", fetchMock);
    show(
      <Routes>
        <Route path="/history/:runId" element={<DetailPage />} />
      </Routes>,
      "/history/run-1",
    );
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "已确认事实" })).toBeVisible(),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/未归档完整日志/)).toBeVisible();
    expect(screen.getByRole("region", { name: "原始问题" })).toHaveTextContent(
      detail.original_message,
    );
    expect(
      screen.getByRole("link", { name: /基于此记录追问/ }),
    ).toHaveAttribute("href", "/?from=run-1");
    fireEvent.click(screen.getByRole("tab", { name: "执行轨迹" }));
    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: "执行轨迹" }),
      ).toHaveTextContent("tool_timeout"),
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("starts a new diagnosis from history without reusing an expired conversation", async () => {
    sessionStorage.setItem("rootlens-history-token", "token");
    const fetchMock = vi
      .fn()
      .mockImplementation((url: string) =>
        Promise.resolve(
          json(url.startsWith("/diagnoses/") ? detail : chatResponse),
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    show(<NewDiagnosis />, "/?from=run-1");
    await waitFor(() =>
      expect(screen.getByRole("region", { name: "历史上下文" })).toBeVisible(),
    );
    expect(screen.getByText(/不会恢复旧会话/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("新的追问"), {
      target: { value: "这条诊断需要先做什么？" },
    });
    fireEvent.click(screen.getByRole("button", { name: /开始诊断/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const first = JSON.parse(
      String((fetchMock.mock.calls[1][1] as RequestInit).body),
    );
    expect(first.message).toContain(detail.original_message);
    expect(first.message).toContain(detail.diagnosis?.summary);
    expect(first.message).toContain("这条诊断需要先做什么？");
    expect(first.conv_id).toBeUndefined();
    expect(first.environment).toBe("demo");
    expect(
      new Headers((fetchMock.mock.calls[1][1] as RequestInit).headers).has(
        "X-RootLens-History-Token",
      ),
    ).toBe(false);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /继续诊断/ })).toBeVisible(),
    );
    fireEvent.change(screen.getByLabelText("故障描述"), {
      target: { value: "还有哪些证据缺口？" },
    });
    fireEvent.click(screen.getByRole("button", { name: /继续诊断/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const second = JSON.parse(
      String((fetchMock.mock.calls[2][1] as RequestInit).body),
    );
    expect(second.message).toBe("还有哪些证据缺口？");
    expect(second.conv_id).toBe("conv-1");
  });

  it("carries a historical clarification into its new follow-up", async () => {
    sessionStorage.setItem("rootlens-history-token", "token");
    const saved = {
      ...detail,
      original_message: "后台界面打不开",
      diagnosis: null,
      clarification_required: true,
      diagnosis_status: "not_run",
    };
    const clarification = {
      ...chatResponse,
      clarification_required: true,
      diagnosis: null,
      diagnosis_status: "not_run",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(saved))
      .mockResolvedValueOnce(json(clarification))
      .mockResolvedValueOnce(json(chatResponse));
    vi.stubGlobal("fetch", fetchMock);
    show(<NewDiagnosis />, "/?from=run-1");
    await waitFor(() =>
      expect(screen.getByLabelText("新的追问")).toBeVisible(),
    );
    fireEvent.change(screen.getByLabelText("新的追问"), {
      target: { value: "补充服务信息" },
    });
    fireEvent.click(screen.getByRole("button", { name: /开始诊断/ }));
    await waitFor(() =>
      expect(screen.getByLabelText("补充信息")).toBeVisible(),
    );
    fireEvent.change(screen.getByLabelText("补充信息"), {
      target: { value: "payment-service 10:05 出现 500" },
    });
    fireEvent.click(screen.getByRole("button", { name: /提交补充/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    const followUp = JSON.parse(
      String((fetchMock.mock.calls[2][1] as RequestInit).body),
    );
    expect(followUp.message).toContain("后台界面打不开");
    expect(followUp.message).toContain("补充服务信息");
    expect(followUp.message).toContain("payment-service 10:05 出现 500");
    expect(followUp.conv_id).toBe("conv-1");
  });

  it("maps backend and network failures without exposing response bodies", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(json({ detail: "SQL path and traceback" }, 503)),
    );
    await expect(api.detail("run-1", "token")).rejects.toMatchObject({
      status: 503,
    });
    const { apiErrorMessage, ApiError } = await import("../lib/api");
    expect(apiErrorMessage(new ApiError(503, "private stack"))).not.toContain(
      "private stack",
    );
  });
});
