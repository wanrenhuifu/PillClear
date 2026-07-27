import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import type { CheckReport as CheckReportData } from "../../../types/api";
import { CheckReport } from "../CheckReport";

const full: CheckReportData = {
  overlap: {
    overlapping: [
      { name: "对乙酰氨基酚", total_amount_mg: 1975, sources: ["泰诺", "白加黑"], max_daily_mg: 4000 },
    ],
    warnings: ["对乙酰氨基酚日总量已超过安全上限"],
  },
  triggered_rules: [
    {
      id: "ibuprofen-alcohol", title: "布洛芬 + 酒精", severity: "danger",
      description: "描述。", warning: "警告文案。", confidence: "high", source: "来源",
    },
  ],
  unresolved_drugs: ["某特效药"],
};

it("三段齐全:警告横幅 / 剂量条 / 规则卡 / 未入库提示", () => {
  render(<CheckReport report={full} />);
  expect(screen.getByText("对乙酰氨基酚日总量已超过安全上限")).toBeInTheDocument();
  expect(screen.getByText("占安全上限 49%")).toBeInTheDocument();
  expect(screen.getByText("警告文案。")).toBeInTheDocument();
  expect(screen.getByText(/某特效药/)).toBeInTheDocument();
});

it("全部为空时渲染安心文案", () => {
  render(
    <CheckReport report={{ overlap: { overlapping: [], warnings: [] }, triggered_rules: [], unresolved_drugs: [] }} />,
  );
  expect(screen.getByText(/未发现叠加或相互作用风险/)).toBeInTheDocument();
});

it("无叠加时显示未发现重复成分", () => {
  render(
    <CheckReport
      report={{ overlap: { overlapping: [], warnings: [] }, triggered_rules: full.triggered_rules, unresolved_drugs: [] }}
    />,
  );
  expect(screen.getByText("未发现重复成分。")).toBeInTheDocument();
});
