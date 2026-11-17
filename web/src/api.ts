/** Клиент API: все запросы через gateway (/api/...). На 401 один раз обновляет токены и повторяет запрос. */
import { session } from "./session";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** detail у FastAPI бывает строкой, списком ошибок валидации или объектом. */
function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => String((item as { msg?: string }).msg ?? item).replace(/^Value error, /, ""))
      .join("; ");
  }
  if (detail && typeof detail === "object") {
    const nested = (detail as { detail?: unknown; error?: unknown }).detail ?? (detail as { error?: unknown }).error;
    if (nested) return String(nested);
  }
  if (status >= 500) return "Сервис временно недоступен, попробуйте позже";
  return `Ошибка ${status}`;
}

let refreshing: Promise<boolean> | null = null;

async function refreshTokens(): Promise<boolean> {
  const token = session.refreshToken;
  if (!token) return false;
  refreshing ??= fetch("/api/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: token }),
  })
    .then(async (resp) => {
      if (!resp.ok) return false;
      const pair = await resp.json();
      session.setTokens(pair.access_token, pair.refresh_token);
      return true;
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export async function api<T = unknown>(method: string, path: string, body?: unknown, retry = true): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (session.accessToken) headers.Authorization = `Bearer ${session.accessToken}`;

  let resp: Response;
  try {
    resp = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "Нет связи с сервером");
  }

  if (resp.status === 401 && retry && session.refreshToken && !path.startsWith("/api/auth/login")) {
    if (await refreshTokens()) return api<T>(method, path, body, false);
    session.clear();
  }
  const text = await resp.text();
  const data = text ? safeJson(text) : null;
  if (!resp.ok) throw new ApiError(resp.status, errorMessage(resp.status, data));
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export const get = <T>(path: string) => api<T>("GET", path);
export const post = <T>(path: string, body?: unknown) => api<T>("POST", path, body);
export const patch = <T>(path: string, body: unknown) => api<T>("PATCH", path, body);
export const put = <T>(path: string, body: unknown) => api<T>("PUT", path, body);
export const del = <T>(path: string) => api<T>("DELETE", path);

export function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const pairs = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "");
  return pairs.length ? "?" + new URLSearchParams(pairs.map(([k, v]) => [k, String(v)])).toString() : "";
}
