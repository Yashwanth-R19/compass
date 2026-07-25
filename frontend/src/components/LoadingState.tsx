export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-slate-500 dark:text-slate-400">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-300 border-t-indigo-500 dark:border-slate-700 dark:border-t-indigo-400" />
      <p className="text-sm">{label}</p>
    </div>
  );
}
