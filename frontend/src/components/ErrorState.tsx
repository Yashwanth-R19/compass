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
      <p className="max-w-sm text-sm text-text-muted">{message}</p>
      {onRetry ? (
        <Button type="button" variant="danger" size="sm" onClick={onRetry} className="mt-2">
          Try again
        </Button>
      ) : null}
    </div>
  );
}
