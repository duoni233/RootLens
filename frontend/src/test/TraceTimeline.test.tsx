import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TraceTimeline } from "../components/TraceTimeline";
import { trace } from "./fixtures";

describe("TraceTimeline", () => {
  it("shows failed, skipped, fallback, error code and overlapping branches", () => {
    render(<TraceTimeline trace={trace} />);
    const steps = screen.getByRole("region", { name: "执行轨迹" });
    expect(steps).toHaveTextContent("意图识别");
    expect(steps).toHaveTextContent("失败");
    expect(steps).toHaveTextContent("跳过");
    expect(steps).toHaveTextContent("tool_timeout");
    expect(steps).toHaveTextContent("已触发 fallback");
    expect(steps).toHaveTextContent("并行");
  });
});
