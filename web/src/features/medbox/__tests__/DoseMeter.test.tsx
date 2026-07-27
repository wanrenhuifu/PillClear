import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { DoseMeter } from "../DoseMeter";

const base = { name: "对乙酰氨基酚", total_amount_mg: 2000, sources: ["泰诺", "白加黑"], max_daily_mg: 4000 };

it("低于 70% 渲染绿色档与占比文案", () => {
  const { container } = render(<DoseMeter item={base} />);
  expect(screen.getByText("占安全上限 50%")).toBeInTheDocument();
  expect(container.querySelector(".bg-pharma")).not.toBeNull();
});

it("70%~100% 渲染琥珀档", () => {
  const { container } = render(<DoseMeter item={{ ...base, total_amount_mg: 3200 }} />);
  expect(screen.getByText("占安全上限 80%")).toBeInTheDocument();
  expect(container.querySelector(".bg-warn")).not.toBeNull();
});

it("超过上限渲染红色档与超限文案", () => {
  const { container } = render(<DoseMeter item={{ ...base, total_amount_mg: 4800 }} />);
  expect(screen.getByText("已超安全上限(约 120%)")).toBeInTheDocument();
  expect(container.querySelector(".bg-danger")).not.toBeNull();
});

it("上限未知渲染中性条与未知提示", () => {
  const { container } = render(<DoseMeter item={{ ...base, max_daily_mg: null }} />);
  expect(screen.getByText(/安全上限未知/)).toBeInTheDocument();
  expect(container.querySelector(".bg-pharma")).toBeNull();
  expect(container.querySelector(".bg-danger")).toBeNull();
});

it("展示来源药品与毫克数", () => {
  render(<DoseMeter item={base} />);
  expect(screen.getByText("来自:泰诺、白加黑")).toBeInTheDocument();
  expect(screen.getByText("2000")).toBeInTheDocument();
});
