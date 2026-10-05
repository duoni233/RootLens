import { describe, expect, it } from "vitest";
import { suggestDemoEventTime } from "../lib/eventTime";

describe("demo event time suggestion", () => {
  it("prefers the incident start over an earlier deployment", () => {
    expect(
      suggestDemoEventTime(
        "payment-service 从 10:05 开始 5xx，v2.3.7 于 10:00 发布",
      ),
    ).toBe("2026-09-01T10:05");
  });

  it("uses an explicit date when present", () => {
    expect(suggestDemoEventTime("2026-09-02 11:30 开始 500")).toBe(
      "2026-09-02T11:30",
    );
  });

  it("does not invent an event time or choose among ambiguous dates", () => {
    expect(suggestDemoEventTime("后台界面打不开")).toBe("");
    expect(suggestDemoEventTime("2026-09-01 和 2026-09-02，10:05 开始")).toBe(
      "",
    );
  });
});
