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
    <div className="flex flex-col items-center justify-center gap-2 border border-sev-high/40 bg-sev-high/5 py-16 text-center">
      <p className="text-sm font-medium text-sev-high">Couldn't load this data</p>
      <p className="max-w-sm text-sm text-ink-muted">{message}</p>
      {onRetry ? (
        <Button type="button" variant="danger" size="sm" onClick={onRetry} className="mt-2">
          Try again
        </Button>
      ) : null}
    </div>
  );
}
