import type {
  ChatResponse,
  CheckReport,
  DrugSummary,
  MedboxItem,
  MedboxResponse,
  ReminderResponse,
} from "../types/api";

export type ApiErrorKind = "llm" | "http" | "network";

export class ApiError extends Error {
  kind: ApiErrorKind;
  status?: number;

  constructor(kind: ApiErrorKind, message: string, status?: number) {
    super(message);
    this.kind = kind;
    this.status = status;
  }
}

const TIMEOUT_MS = 60_000;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(path, { ...init, signal: controller.signal });
  } catch (err) {
    const message =
      err instanceof DOMException && err.name === "AbortError"
        ? "请求超时"
        : "网络异常";
    throw new ApiError("network", message);
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    if (res.status === 502) {
      throw new ApiError("llm", "AI 服务暂时不可用", 502);
    }
    throw new ApiError("http", `服务异常(${res.status})`, res.status);
  }
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const getHealth = () => request<{ status: string }>("/api/v1/health");

export const postChat = (query: string) =>
  request<ChatResponse>("/api/v1/chat", json({ query }));

export const listDrugs = () => request<DrugSummary[]>("/api/v1/drugs");

export const getMedbox = (deviceId: string) =>
  request<MedboxResponse>(`/api/v1/medbox/${deviceId}`);

export const addMedboxItem = (
  deviceId: string,
  item: { drug_id: number; brand_name: string; dosage_per_day: number | null },
) => request<MedboxResponse>(`/api/v1/medbox/${deviceId}/items`, json(item));

export const removeMedboxItem = (deviceId: string, drugId: number) =>
  request<MedboxResponse>(`/api/v1/medbox/${deviceId}/items/${drugId}`, {
    method: "DELETE",
  });

export const checkMedbox = (items: MedboxItem[], lifestyleSubstances: string[]) =>
  request<CheckReport>("/api/v1/medbox/check", json({
    items,
    lifestyle_substances: lifestyleSubstances,
  }));

export const getReminders = (deviceId: string) =>
  request<ReminderResponse>(`/api/v1/reminders/${deviceId}`);

export const setReminder = (
  deviceId: string,
  item: { drug_id: number; brand_name: string; times: string[] },
) => request<ReminderResponse>(`/api/v1/reminders/${deviceId}/items`, json(item));

export const removeReminder = (deviceId: string, drugId: number) =>
  request<ReminderResponse>(`/api/v1/reminders/${deviceId}/items/${drugId}`, {
    method: "DELETE",
  });
