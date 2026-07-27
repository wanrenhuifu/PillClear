import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { DrugPicker } from "../DrugPicker";
import { SUBSTANCES, SubstanceChips } from "../SubstanceChips";

const drugs = [
  { drug_id: 1, brand_name: "泰诺", generic_name: "酚麻美敏片" },
  { drug_id: 2, brand_name: "芬必得", generic_name: "布洛芬缓释胶囊" },
];

it("按商品名与通用名过滤", async () => {
  render(<DrugPicker drugs={drugs} inBoxIds={new Set()} onAdd={() => {}} />);
  const user = userEvent.setup();

  await user.type(screen.getByPlaceholderText(/搜索药品/), "芬");
  expect(screen.getByText("芬必得")).toBeInTheDocument();
  expect(screen.queryByText("泰诺")).not.toBeInTheDocument();

  await user.clear(screen.getByPlaceholderText(/搜索药品/));
  await user.type(screen.getByPlaceholderText(/搜索药品/), "酚麻");
  expect(screen.getByText("泰诺")).toBeInTheDocument();
});

it("已在药箱的药显示为禁用状态", () => {
  render(<DrugPicker drugs={drugs} inBoxIds={new Set([1])} onAdd={() => {}} />);
  expect(screen.getByRole("button", { name: "已在药箱" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "加入" })).toBeEnabled();
});

it("默认日频次 1,确认后回调", async () => {
  const onAdd = vi.fn();
  render(<DrugPicker drugs={drugs} inBoxIds={new Set()} onAdd={onAdd} />);
  const user = userEvent.setup();

  await user.click(screen.getAllByRole("button", { name: "加入" })[0]);
  await user.click(screen.getByRole("button", { name: "确认加入" }));

  expect(onAdd).toHaveBeenCalledWith(drugs[0], 1);
});

it("stepper 可加减且有上下界", async () => {
  const onAdd = vi.fn();
  render(<DrugPicker drugs={drugs} inBoxIds={new Set()} onAdd={onAdd} />);
  const user = userEvent.setup();

  await user.click(screen.getAllByRole("button", { name: "加入" })[0]);
  await user.click(screen.getByRole("button", { name: "增加频次" }));
  await user.click(screen.getByRole("button", { name: "增加频次" }));
  await user.click(screen.getByRole("button", { name: "确认加入" }));

  expect(onAdd).toHaveBeenCalledWith(drugs[0], 3);
});

it("勾选不确定频次后 dosage 传 null", async () => {
  const onAdd = vi.fn();
  render(<DrugPicker drugs={drugs} inBoxIds={new Set()} onAdd={onAdd} />);
  const user = userEvent.setup();

  await user.click(screen.getAllByRole("button", { name: "加入" })[0]);
  await user.click(screen.getByRole("checkbox", { name: "不确定频次" }));
  await user.click(screen.getByRole("button", { name: "确认加入" }));

  expect(onAdd).toHaveBeenCalledWith(drugs[0], null);
});

it("物质 chip 恰好两个且可切换", async () => {
  const onToggle = vi.fn();
  render(<SubstanceChips selected={["酒精"]} onToggle={onToggle} />);
  expect(SUBSTANCES).toEqual(["酒精", "避孕药"]);
  expect(screen.getByRole("button", { name: "酒精" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.setup().click(screen.getByRole("button", { name: "避孕药" }));
  expect(onToggle).toHaveBeenCalledWith("避孕药");
});
