import { ApiError } from "../api/client";

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : "Something went wrong.";

  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-red-200 bg-red-50 py-16 text-center dark:border-red-500/30 dark:bg-red-500/10">
      <p className="text-sm font-medium text-red-700 dark:text-red-400">Couldn't load this data</p>
      <p className="max-w-sm text-sm text-red-600/80 dark:text-red-400/70">{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700"
        >
          Try again
        </button>
      ) : null}
    </div>
  );
}
