import { Link, Outlet } from "react-router-dom";

export function AppShell() {
  return (
    <div className="min-h-full">
      <header className="border-b border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
          <Link to="/" className="flex items-center gap-2 text-slate-900 dark:text-slate-100">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-indigo-600 text-sm font-bold text-white">
              C
            </span>
            <span className="text-sm font-semibold tracking-tight">Compass</span>
          </Link>
          <Link
            to="/"
            className="rounded-md border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
          >
            Analyze a repo
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
        <Outlet />
      </main>
    </div>
  );
}
