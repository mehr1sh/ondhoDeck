"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";

export interface QueryState<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  /** Re-runs the loader. Keeps current data visible while reloading. */
  reload: () => Promise<T | undefined>;
  setData: (updater: T | ((prev: T | undefined) => T)) => void;
}

/**
 * Loads data with `loader` whenever `deps` change. Ignores stale responses.
 * Pass `enabled=false` to skip loading (e.g. when an id is not yet known).
 */
export function useApiQuery<T>(
  loader: () => Promise<T>,
  deps: unknown[],
  enabled = true,
): QueryState<T> {
  const [data, setDataState] = useState<T | undefined>(undefined);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState<boolean>(enabled);
  const seq = useRef(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const run = useCallback(async (): Promise<T | undefined> => {
    const id = ++seq.current;
    setLoading(true);
    try {
      const result = await loaderRef.current();
      if (id === seq.current) {
        setDataState(result);
        setError(null);
      }
      return result;
    } catch (e) {
      if (id === seq.current) setError(e);
      return undefined;
    } finally {
      if (id === seq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    void run();
    const counter = seq;
    return () => {
      // Invalidate in-flight requests from the previous deps.
      counter.current++;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, run, ...deps]);

  const setData = useCallback((updater: T | ((prev: T | undefined) => T)) => {
    setDataState((prev) =>
      typeof updater === "function" ? (updater as (p: T | undefined) => T)(prev) : updater,
    );
  }, []);

  return { data, error, loading, reload: run, setData };
}

/** Calls `tick` every `intervalMs` while `active` is true. */
export function usePolling(tick: () => void | Promise<void>, intervalMs: number, active: boolean) {
  const tickRef = useRef(tick);
  tickRef.current = tick;
  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const loop = async () => {
      if (cancelled) return;
      try {
        await tickRef.current();
      } finally {
        if (!cancelled) timer = setTimeout(loop, intervalMs);
      }
    };
    timer = setTimeout(loop, intervalMs);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [active, intervalMs]);
}

export interface DescribedError {
  title: string;
  message: string;
  requestId: string | null;
  status: number | null;
  code: string | null;
}

export function describeError(e: unknown): DescribedError {
  if (e instanceof ApiError) {
    const titles: Record<number, string> = {
      0: "Connection problem",
      401: "Session expired",
      403: "Access denied",
      404: "Not found",
      409: "Conflict",
      413: "File too large",
      415: "Unsupported file type",
      422: "Please check the highlighted fields",
      429: "Too many requests",
    };
    let message = e.message;
    if (e.status === 403) message = e.message || "You do not have permission to do this.";
    if (e.status === 429 && e.retryAfter) message = `${e.message} Try again in ${e.retryAfter} seconds.`;
    return {
      title: titles[e.status] ?? (e.status >= 500 ? "Something went wrong on our side" : "Request failed"),
      message,
      requestId: e.requestId,
      status: e.status,
      code: e.code,
    };
  }
  if (e instanceof Error) {
    return { title: "Something went wrong", message: e.message, requestId: null, status: null, code: null };
  }
  return { title: "Something went wrong", message: "Unexpected error.", requestId: null, status: null, code: null };
}
