import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { Badge } from "../Badge";
import { CapsuleButton } from "../CapsuleButton";
import { Chip } from "../Chip";
import { EmptyState } from "../EmptyState";
import { Logo } from "../Logo";
import { SectionTitle } from "../SectionTitle";

it("Chip 反映 pressed 状态并响应点击", async () => {
  const onClick = vi.fn();
  render(<Chip active onClick={onClick}>酒精</Chip>);
  const chip = screen.getByRole("button", { name: "酒精" });
  expect(chip).toHaveAttribute("aria-pressed", "true");
  await userEvent.setup().click(chip);
  expect(onClick).toHaveBeenCalledTimes(1);
});

it("CapsuleButton disabled 时不触发点击", async () => {
  const onClick = vi.fn();
  render(<CapsuleButton disabled onClick={onClick}>发送</CapsuleButton>);
  await userEvent.setup().click(screen.getByRole("button", { name: "发送" }));
  expect(onClick).not.toHaveBeenCalled();
});

it("Badge 渲染子内容", () => {
  render(<Badge tone="danger">危险</Badge>);
  expect(screen.getByText("危险")).toBeInTheDocument();
});

it("SectionTitle 渲染 h2", () => {
  render(<SectionTitle>成分叠加</SectionTitle>);
  expect(screen.getByRole("heading", { level: 2, name: "成分叠加" })).toBeInTheDocument();
});

it("EmptyState 渲染标题与提示", () => {
  render(<EmptyState title="药箱是空的" hint="先添加你正在吃的药" />);
  expect(screen.getByText("药箱是空的")).toBeInTheDocument();
  expect(screen.getByText("先添加你正在吃的药")).toBeInTheDocument();
});

it("Logo 带无障碍标签", () => {
  render(<Logo />);
  expect(screen.getByLabelText("PillClear")).toBeInTheDocument();
});
