import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import * as api from "./lib/api";
import { AppRoutes } from "./App";

vi.mock("./lib/api");
vi.mock("./lib/device", () => ({ getDeviceId: () => "dev-test" }));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listDrugs).mockResolvedValue([]);
  vi.mocked(api.getMedbox).mockResolvedValue({ device_id: "dev-test", items: [] });
});

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("/chat 渲染聊天视图与药箱侧栏入口", async () => {
  renderAt("/chat");
  expect(screen.getByText("PillClear")).toBeInTheDocument();
  expect(await screen.findByText("试试这些常见问题")).toBeInTheDocument();
  expect(screen.getAllByText("我的药箱").length).toBeGreaterThan(0);
});

it("/medbox 渲染全页药箱(含选择器)", async () => {
  renderAt("/medbox");
  expect(await screen.findByText("添加药品")).toBeInTheDocument();
});

it("底部 tab 可在两个视图间切换", async () => {
  renderAt("/chat");
  const user = userEvent.setup();
  await user.click(screen.getByRole("link", { name: "药箱" }));
  expect(await screen.findByText("添加药品")).toBeInTheDocument();
});
