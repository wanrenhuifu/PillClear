import { expect, it } from "vitest";
import { formatDueLabel, formatMg } from "../format";

it("整数省略小数", () => {
  expect(formatMg(1975)).toBe("1975");
  expect(formatMg(4000)).toBe("4000");
});

it("非整数保留一位", () => {
  expect(formatMg(325.5)).toBe("325.5");
});

// formatDueLabel：显式传 now，不依赖系统时钟（同后端 next_due 的纯函数纪律）
const NOW = new Date(2026, 7, 10, 9, 0); // 2026-08-10 09:00

it("今天/明天/更远的提醒时刻分档展示", () => {
  expect(formatDueLabel("2026-08-10T20:00:00", NOW)).toBe("今天 20:00");
  expect(formatDueLabel("2026-08-11T08:00:00", NOW)).toBe("明天 08:00");
  expect(formatDueLabel("2026-08-12T08:00:00", NOW)).toBe("08-12 08:00");
});

it("无法解析的时刻返回原串不崩", () => {
  expect(formatDueLabel("not-a-date", NOW)).toBe("not-a-date");
});
