const KEY = "pillclear_device_id";

/** MVP 用户标识:首次访问生成 UUID 并持久化,后续读取同一值。 */
export function getDeviceId(): string {
  const existing = localStorage.getItem(KEY);
  if (existing) return existing;
  const id = crypto.randomUUID();
  localStorage.setItem(KEY, id);
  return id;
}
