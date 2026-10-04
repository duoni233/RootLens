import type { DiagnosisBuildStatus, HistorySummary } from "./types";

export function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }).format(date);
}

export function displayStatus(status: string): string {
  const labels: Record<string, string> = {
    success: "成功",
    failed: "失败",
    degraded: "降级",
    skipped: "跳过",
    empty: "无结果",
    ok: "正常",
    not_run: "未执行",
    validation_failed: "校验失败",
    parse_failed: "解析失败",
    assembler_failed: "生成失败",
    saved: "已保存",
    disabled: "未启用",
    clarification: "待补充信息",
  };
  return labels[status] ?? status.replaceAll("_", " ");
}

export function runStatus(
  run: Pick<
    HistorySummary,
    "clarification_required" | "diagnosis_status" | "degraded"
  >,
): string {
  if (run.clarification_required) return "clarification";
  if (run.diagnosis_status !== "success") return run.diagnosis_status;
  return run.degraded ? "degraded" : "success";
}

export const buildStatuses: DiagnosisBuildStatus[] = [
  "success",
  "not_run",
  "validation_failed",
  "parse_failed",
  "assembler_failed",
];
