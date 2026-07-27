import { expect, it } from "vitest";
import { formatMg } from "../format";

it("整数省略小数", () => {
  expect(formatMg(1975)).toBe("1975");
  expect(formatMg(4000)).toBe("4000");
});

it("非整数保留一位", () => {
  expect(formatMg(325.5)).toBe("325.5");
});
