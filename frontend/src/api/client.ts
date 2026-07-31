const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

/** Discriminated result for endpoints that can answer "not computed yet"
 * (HTTP 202, see Part E of the Phase 02 staged-pipeline spec) instead of
 * throwing -- a 202 is not an error, it's the frontend's signal to render a
 * skeleton rather than an empty state for a stage that hasn't finished. */
export type PendingResult = { kind: "pending"; stage: string; status: string };
export type DataResult<T> = { kind: "data"; data: T };
export type FetchResult<T> = DataResult<T> | PendingResult;

async function parseErrorMessage(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: string };
    return body.detail ?? res.statusText;
  } catch {
    return res.statusText;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!res.ok) {
    throw new ApiError(res.status, await parseErrorMessage(res));
  }

  return res.json() as Promise<T>;
}

/** Like `request`, but treats HTTP 202 as a valid, non-error outcome and
 * wraps every response in a `{ kind }` discriminator instead of returning
 * the body directly -- used only by the run-scoped analysis endpoints
 * (coupling/architecture/hidden-dependencies/risk/health/findings), which
 * are the ones that can be "not computed yet for this run". */
async function requestOrPending<T>(path: string, init?: RequestInit): Promise<FetchResult<T>> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (res.status === 202) {
    const body = (await res.json()) as { stage: string; status: string };
    return { kind: "pending", stage: body.stage, status: body.status };
  }

  if (!res.ok) {
    throw new ApiError(res.status, await parseErrorMessage(res));
  }

  return { kind: "data", data: (await res.json()) as T };
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path, { method: "GET" });
}

export function apiGetOrPending<T>(path: string): Promise<FetchResult<T>> {
  return requestOrPending<T>(path, { method: "GET" });
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(body) });
}
