import { ApiError } from "../api/client";
import { Button } from "./ui/Button";

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : "Something went wrong.";

  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-danger/40 bg-danger-bg py-16 text-center">
      <p className="text-sm font-medium text-danger">Couldn't load this data</p>
      {/* text-text, not text-muted -- this session's own accessibility
          sweep measured text-muted at only 4.36:1 against bg-danger-bg in
          the light scheme (real data: an "Not authenticated." error
          message), just under the 4.5:1 body-text bar. */}
      <p className="max-w-sm text-sm text-text">{message}</p>
      {onRetry ? (
        <Button type="button" variant="danger" size="sm" onClick={onRetry} className="mt-2">
          Try again
        </Button>
      ) : null}
    </div>
  );
}
