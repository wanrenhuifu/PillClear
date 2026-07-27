/** 剂量数字格式化:整数不带小数点(1975.0 → "1975"),否则保留一位。 */
export function formatMg(mg: number): string {
  return Number.isInteger(mg) ? String(mg) : mg.toFixed(1);
}
