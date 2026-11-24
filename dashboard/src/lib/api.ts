import { clearAccessToken, getAccessToken } from "@/lib/auth";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function parseErrorDetail(resp: Response): Promise<string> {
  try {
    const body = (await resp.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      return body.detail;
    }
    if (Array.isArray(body.detail) && body.detail.length > 0) {
      const first = body.detail[0] as { msg?: string };
      if (first.msg) return first.msg;
    }
  } catch {
    // Fallback to status text below.
  }
  return `คำขอไม่สำเร็จ (HTTP ${resp.status})`;
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit & { skipAuth?: boolean } = {},
): Promise<T> {
  const { skipAuth = false, headers: rawHeaders, ...rest } = options;
  const headers = new Headers(rawHeaders);

  if (!skipAuth) {
    const token = getAccessToken();
    if (token) {
      headers.set("Authorization", `Bearer ${token}`);
    }
  }
  if (rest.body && !(rest.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const resp = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    headers,
    cache: "no-store",
  });

  if (resp.status === 401 && !skipAuth && typeof window !== "undefined") {
    clearAccessToken();
  }
  if (!resp.ok) {
    throw new ApiError(resp.status, await parseErrorDetail(resp));
  }
  if (resp.status === 204) {
    return undefined as T;
  }
  return (await resp.json()) as T;
}

export async function apiUpload<T>(path: string, file: File): Promise<T> {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch<T>(path, { method: "POST", body: formData });
}
