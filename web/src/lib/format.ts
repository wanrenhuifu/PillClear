/** 剂量数字格式化:整数不带小数点(1975.0 → "1975"),否则保留一位。 */
export function formatMg(mg: number): string {
  return Number.isInteger(mg) ? String(mg) : mg.toFixed(1);
}

/** 提醒时刻展示:今天 → "今天 20:00",明天 → "明天 08:00",
 *  更远 → "08-12 08:00"。解析失败返回原始串(不崩,铁律:不确定就明说)。 */
export function formatDueLabel(iso: string, now: Date = new Date()): string {
  const due = new Date(iso);
  if (Number.isNaN(due.getTime())) return iso;
  const hhmm = `${String(due.getHours()).padStart(2, "0")}:${String(due.getMinutes()).padStart(2, "0")}`;
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  if (sameDay(due, now)) return `今天 ${hhmm}`;
  if (sameDay(due, tomorrow)) return `明天 ${hhmm}`;
  const mmdd = `${String(due.getMonth() + 1).padStart(2, "0")}-${String(due.getDate()).padStart(2, "0")}`;
  return `${mmdd} ${hhmm}`;
}
