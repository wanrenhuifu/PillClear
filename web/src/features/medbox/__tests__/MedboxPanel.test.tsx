import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactNode } from "react";
import * as api from "../../../lib/api";
import { MedboxPanel } from "../MedboxPanel";

vi.mock("../../../lib/api");
vi.mock("../../../lib/device", () => ({ getDeviceId: () => "dev-1" }));

const drugs = [
  { drug_id: 1, brand_name: "泰诺", generic_name: "酚麻美敏片" },
  { drug_id: 2, brand_name: "芬必得", generic_name: "布洛芬缓释胶囊" },
];

const report = {
  overlap: { overlapping: [], warnings: [] },
  triggered_rules: [],
  unresolved_drugs: [],
};

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
  vi.mocked(api.getMedbox).mockResolvedValue({ device_id: "dev-1", items: [] });
  vi.mocked(api.addMedboxItem).mockResolvedValue({
    device_id: "dev-1",
    items: [{ drug_id: 1, brand_name: "泰诺", dosage_per_day: 3 }],
  });
  vi.mocked(api.removeMedboxItem).mockResolvedValue({ device_id: "dev-1", items: [] });
  vi.mocked(api.checkMedbox).mockResolvedValue(report);
});

it("full 变体渲染选择器,加入药品后上送并刷新列表", async () => {
  render(<MedboxPanel variant="full" />, { wrapper });
  const user = userEvent.setup();

  expect(await screen.findByText("芬必得")).toBeInTheDocument();
  // 两个药各有一个「加入」按钮,取第一个(泰诺)
  await user.click(screen.getAllByRole("button", { name: "加入" })[0]);
  await user.click(screen.getByRole("button", { name: "确认加入" }));

  expect(api.addMedboxItem).toHaveBeenCalledWith("dev-1", {
    drug_id: 1, brand_name: "泰诺", dosage_per_day: 1,
  });
  // invalidate 触发药箱重取
  await waitFor(() => expect(api.getMedbox).toHaveBeenCalledTimes(2));
});

it("检查按钮上送当前药箱与所选物质,渲染报告", async () => {
  vi.mocked(api.getMedbox).mockResolvedValue({
    device_id: "dev-1",
    items: [{ drug_id: 1, brand_name: "泰诺", dosage_per_day: 3 }],
  });
  render(<MedboxPanel variant="rail" />, { wrapper });
  const user = userEvent.setup();

  await screen.findByText("泰诺");
  await user.click(screen.getByRole("button", { name: "酒精" }));
  await user.click(screen.getByRole("button", { name: "开始检查" }));

  await waitFor(() =>
    expect(api.checkMedbox).toHaveBeenCalledWith(
      [{ drug_id: 1, brand_name: "泰诺", dosage_per_day: 3 }],
      ["酒精"],
    ),
  );
  expect(await screen.findByText(/未发现叠加或相互作用风险/)).toBeInTheDocument();
});

it("移除药品调用 DELETE 并刷新", async () => {
  vi.mocked(api.getMedbox).mockResolvedValue({
    device_id: "dev-1",
    items: [{ drug_id: 1, brand_name: "泰诺", dosage_per_day: null }],
  });
  render(<MedboxPanel variant="rail" />, { wrapper });
  const user = userEvent.setup();

  expect(await screen.findByText("频次未定")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "移除泰诺" }));

  expect(api.removeMedboxItem).toHaveBeenCalledWith("dev-1", 1);
  await waitFor(() => expect(api.getMedbox).toHaveBeenCalledTimes(2));
});

it("空药箱禁用检查按钮并显示空态", async () => {
  render(<MedboxPanel variant="full" />, { wrapper });
  await screen.findByText("芬必得");
  expect(screen.getByText("药箱是空的")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "开始检查" })).toBeDisabled();
});
