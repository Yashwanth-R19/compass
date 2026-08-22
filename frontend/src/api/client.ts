const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

/** Thrown for a 403 on a repo-scoped endpoint -- distinguishable from a
 * generic ApiError so the UI can show a "Connect private repositories"
 * button instead of a plain error state (session 02, Part G). */
export class NeedsPrivateAccessError extends ApiError {
  constructor(message: string) {
    super(403, message);
    this.name = "NeedsPrivateAccessError";
  }
}

/** Thrown for a 429 -- carries the server's `Retry-After` hint so the UI
 * can show "try again in Ns" instead of a raw error (session 02, Part G). */
export class RateLimitedError extends ApiError {
  retryAfterSeconds: number;

  constructor(message: string, retryAfterSeconds: number) {
    super(429, message);
    this.name = "RateLimitedError";
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

/** Discriminated result for endpoints that can answer "not computed yet"
 * (HTTP 202, see Part E of the Phase 02 staged-pipeline spec) instead of
 * throwing -- a 202 is not an error, it's the frontend's signal to render a
 * skeleton rather than an empty state for a stage that hasn't finished. */
export type PendingResult = { kind: "pending"; stage: string; status: string };
export type DataResult<T> = { kind: "data"; data: T };
export type FetchResult<T> = DataResult<T> | PendingResult;

// Session 02: a lightweight pub-sub so client.ts (which has no react-query
// dependency of its own) can tell the rest of the app "the session cookie
// is no longer valid" without importing the query client directly --
// useMe() subscribes to this and clears its cached user on the spot,
// per Part G's "handle 401 by clearing cached user state."
type UnauthorizedListener = () => void;
const unauthorizedListeners = new Set<UnauthorizedListener>();

export function onUnauthorized(listener: UnauthorizedListener): () => void {
  unauthorizedListeners.add(listener);
  return () => {
    unauthorizedListeners.delete(listener);
  };
}

function notifyUnauthorized() {
  for (const listener of unauthorizedListeners) listener();
}

async function parseErrorMessage(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: string };
    return body.detail ?? res.statusText;
  } catch {
    return res.statusText;
  }
}

function retryAfterSeconds(res: Response): number {
  const header = res.headers.get("Retry-After");
  const parsed = header ? Number(header) : NaN;
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0;
}

/** Throws the right ApiError subclass for a non-2xx response, and fires the
 * onUnauthorized pub-sub for a 401 -- shared by both `request` and
 * `requestOrPending` so every endpoint handles 401/403/429 identically. */
async function throwForResponse(res: Response): Promise<never> {
  if (res.status === 401) {
    notifyUnauthorized();
  }
  const message = await parseErrorMessage(res);
  if (res.status === 403) {
    throw new NeedsPrivateAccessError(message);
  }
  if (res.status === 429) {
    throw new RateLimitedError(message, retryAfterSeconds(res));
  }
  throw new ApiError(res.status, message);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    // Every request carries the session cookie -- the API and frontend are
    // different sites (Render/Vercel), so this is required for the cookie
    // to be sent at all, not just a nicety (session 02, Part G).
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!res.ok) {
    return throwForResponse(res);
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
    credentials: "include",
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
    return throwForResponse(res);
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

export function apiDelete<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}

/** Builds the URL for the "Log in with GitHub" / "Connect private
 * repositories" buttons -- a plain top-level navigation (an <a href>, not a
 * fetch), since the OAuth flow's SameSite=Lax state cookie depends on this
 * being a real top-level GET (see app/auth/session.py's docstring on the
 * backend). `next` is validated server-side; this only forwards it. */
export function githubLoginUrl(scope: "basic" | "repo", next?: string): string {
  const params = new URLSearchParams({ scope });
  if (next) params.set("next", next);
  return `${API_URL}/auth/github/login?${params.toString()}`;
}
