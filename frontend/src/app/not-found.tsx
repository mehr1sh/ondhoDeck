import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-page p-4">
      <div className="w-full max-w-md rounded-md border border-line bg-surface p-6 text-center">
        <p className="text-sm font-semibold uppercase tracking-wide text-slate-500">404</p>
        <h1 className="font-display mt-1 text-2xl text-ink">Page not found</h1>
        <p className="mt-2 text-sm text-slate-600">The page you requested does not exist in OndhoDeck.</p>
        <Link
          href="/"
          className="mt-4 inline-flex rounded-md border border-accent bg-accent px-3 py-2 text-sm font-medium text-white hover:bg-accent-hover"
        >
          Go to overview
        </Link>
      </div>
    </main>
  );
}
