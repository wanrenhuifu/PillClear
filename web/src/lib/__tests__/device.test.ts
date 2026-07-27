import { beforeEach, expect, it, vi } from "vitest";
import { getDeviceId } from "../device";

beforeEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

it("首次调用生成并持久化", () => {
  vi.stubGlobal("crypto", { randomUUID: () => "uuid-1234" });
  expect(getDeviceId()).toBe("uuid-1234");
  expect(localStorage.getItem("pillclear_device_id")).toBe("uuid-1234");
});

it("二次调用读取已有值,不重新生成", () => {
  const gen = vi.fn(() => "new-uuid");
  vi.stubGlobal("crypto", { randomUUID: gen });
  localStorage.setItem("pillclear_device_id", "existing");
  expect(getDeviceId()).toBe("existing");
  expect(gen).not.toHaveBeenCalled();
});
