import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import type { TriggeredRule } from "../../../types/api";
import { RuleCard } from "../RuleCard";

const base: TriggeredRule = {
  id: "ibuprofen-alcohol",
  title: "布洛芬 + 酒精:伤胃又伤肝",
  severity: "danger",
  description: "两者同用显著增加消化道出血风险。",
  warning: "服用布洛芬期间饮酒会加重胃黏膜损伤,请避免饮酒。",
  confidence: "high",
  source: "药品说明书【注意事项】",
};

it("danger 渲染危险徽章并原样展示 warning 文案", () => {
  render(<RuleCard rule={base} />);
  expect(screen.getByText("危险")).toBeInTheDocument();
  expect(screen.getByText(base.warning)).toBeInTheDocument();
  expect(screen.getByText(base.source!)).toBeInTheDocument();
});

it("warning / info 渲染对应徽章", () => {
  render(<RuleCard rule={{ ...base, id: "w", severity: "warning" }} />);
  expect(screen.getByText("注意")).toBeInTheDocument();
});

it("证据强度映射为中文徽章,medium/low 带保守提示", () => {
  render(<RuleCard rule={{ ...base, id: "m", confidence: "medium" }} />);
  const badge = screen.getByText("证据中等");
  expect(badge).toHaveAttribute("title", "证据有限,保守提示");
});

it("high 证据不带保守提示 tooltip", () => {
  render(<RuleCard rule={base} />);
  expect(screen.getByText("证据充分")).not.toHaveAttribute("title");
});
