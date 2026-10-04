import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import {
  DiagnosisView,
  type DiagnosisViewProps,
} from "../components/DiagnosisView";
import { chatResponse, diagnosis } from "./fixtures";

function props(
  overrides: Partial<DiagnosisViewProps> = {},
): DiagnosisViewProps {
  return {
    diagnosis,
    markdown: chatResponse.response,
    diagnosisStatus: "success",
    intent: "deployment_issue",
    primaryAgent: "application",
    supportingAgents: ["database"],
    serviceName: "payment-service",
    environment: "demo",
    runId: "run-1",
    persistenceStatus: "saved",
    degraded: false,
    clarificationRequired: false,
    evidenceRefs: diagnosis.evidence_refs,
    knowledgeRefs: diagnosis.knowledge_refs,
    toolStatus: diagnosis.tool_status,
    ...overrides,
  };
}

function show(overrides: Partial<DiagnosisViewProps> = {}) {
  render(
    <MemoryRouter>
      <DiagnosisView {...props(overrides)} />
    </MemoryRouter>,
  );
}

describe("DiagnosisView", () => {
  it("separates confirmed findings, hypotheses, operational evidence, and knowledge", () => {
    show();
    expect(
      screen.getByRole("region", { name: "已确认事实" }),
    ).toHaveTextContent("DBConnectionError");
    expect(
      screen.getByRole("region", { name: "待验证假设" }),
    ).toHaveTextContent("发布可能");
    expect(
      screen.getByRole("region", { name: "现场证据引用" }),
    ).toHaveTextContent("E-LOG-001");
    expect(
      screen.getByRole("region", { name: "知识来源引用" }),
    ).toHaveTextContent("runbooks/db-pool.md");
    expect(screen.getByText("需审批")).toBeVisible();
    expect(screen.getByText("HIGH 风险")).toBeVisible();
  });

  it("renders clarification without empty diagnosis sections", () => {
    show({
      diagnosis: {
        ...diagnosis,
        status: "clarification",
        clarification_required: true,
        clarification_question: "请提供服务名和时间。",
      },
      clarificationRequired: true,
    });
    expect(screen.getByRole("region", { name: "澄清问题" })).toHaveTextContent(
      "请提供服务名和时间",
    );
    expect(
      screen.queryByRole("region", { name: "已确认事实" }),
    ).not.toBeInTheDocument();
  });

  it("keeps Markdown when structured diagnosis failed and shows persistence failure", () => {
    show({
      diagnosis: null,
      diagnosisStatus: "parse_failed",
      persistenceStatus: "failed",
      runId: null,
      evidenceRefs: [],
      untypedEvidenceIds: ["E-LOG-001"],
      knowledgeRefs: [],
    });
    expect(
      screen.getByRole("region", { name: "非结构化回复" }),
    ).toHaveTextContent("parse_failed");
    expect(screen.getByText("诊断已返回，但本次未保存到历史。")).toBeVisible();
    expect(screen.getByText(/连接池异常/)).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "现场证据引用" }),
    ).toHaveTextContent("类型未返回");
  });

  it("distinguishes empty tool output from a failed tool", () => {
    show({
      toolStatus: { query_logs: "empty", query_metrics: "failed" },
      degraded: true,
    });
    const tools = screen.getByRole("region", { name: "工具状态" });
    expect(tools).toHaveTextContent("无结果");
    expect(tools).toHaveTextContent("失败");
    expect(screen.getByRole("region", { name: "诊断概览" })).toHaveTextContent(
      "降级",
    );
  });
});
