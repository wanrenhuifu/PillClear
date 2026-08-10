import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import * as api from "../../../lib/api";
import { ReminderPanel } from "../ReminderPanel";

vi.mock("../../../lib/api");
vi.mock("../../../lib/device", () => ({ getDeviceId: () => "dev-1" }));

const drugs = [
  { drug_id: 1, brand_name: "泰诺", generic_name: "酚麻美敏片" },
  { drug_id: 2, brand_name: "芬必得", generic_name: "布洛芬缓释胶囊" },
];

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listDrugs).mockResolvedValue(drugs);
  vi.mocked(api.getReminders).mockResolvedValue({ device_id: "dev-1", reminders: [] });
  vi.mocked(api.setReminder).mockResolvedValue({
    device_id: "dev-1",
    reminders: [
      { drug_id: 1, brand_name: "泰诺", times: ["08:00"], next_due_at: "2026-08-11T08:00:00" },
    ],
  });
  vi.mocked(api.removeReminder).mockResolvedValue({ device_id: "dev-1", reminders: [] });
});

it("选药设时刻表后上送并刷新列表", async () => {
  render(<ReminderPanel />, { wrapper });
  const user = userEvent.setup();

  expect(await screen.findByText("芬必得")).toBeInTheDocument();
  await user.click(screen.getAllByRole("button", { name: "设提醒" })[0]);
  await user.click(screen.getByRole("button", { name: "确认设置" }));

  expect(api.setReminder).toHaveBeenCalledWith("dev-1", {
    drug_id: 1,
    brand_name: "泰诺",
    times: ["08:00"],
  });
  // invalidate 触发提醒列表重取
  await waitFor(() => expect(api.getReminders).toHaveBeenCalledTimes(2));
});

it("已有提醒渲染时刻与下次提醒,可删除", async () => {
  vi.mocked(api.getReminders).mockResolvedValue({
    device_id: "dev-1",
    reminders: [
      {
        drug_id: 1,
        brand_name: "泰诺",
        times: ["08:00", "20:00"],
        next_due_at: "2026-08-11T08:00:00",
      },
    ],
  });
  render(<ReminderPanel />, { wrapper });
  const user = userEvent.setup();

  await screen.findAllByText("泰诺");
  expect(screen.getByText("08:00")).toBeInTheDocument();
  expect(screen.getByText("20:00")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "删除泰诺的提醒" }));
  expect(api.removeReminder).toHaveBeenCalledWith("dev-1", 1);
});

it("已设提醒的药品按钮变为「改时间」", async () => {
  vi.mocked(api.getReminders).mockResolvedValue({
    device_id: "dev-1",
    reminders: [
      { drug_id: 1, brand_name: "泰诺", times: ["08:00"], next_due_at: null },
    ],
  });
  render(<ReminderPanel />, { wrapper });

  await screen.findAllByText("泰诺");
  expect(screen.getByRole("button", { name: "改时间" })).toBeInTheDocument();
});

it("可加时刻至 4 个上限", async () => {
  render(<ReminderPanel />, { wrapper });
  const user = userEvent.setup();

  await screen.findByText("芬必得");
  await user.click(screen.getAllByRole("button", { name: "设提醒" })[0]);
  await user.click(screen.getByRole("button", { name: "+ 加一个时刻" }));
  await user.click(screen.getByRole("button", { name: "确认设置" }));

  expect(api.setReminder).toHaveBeenCalledWith("dev-1", {
    drug_id: 1,
    brand_name: "泰诺",
    times: ["08:00", "12:00"],
  });
});
